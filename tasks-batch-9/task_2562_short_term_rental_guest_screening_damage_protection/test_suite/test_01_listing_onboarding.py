"""Jurisdiction rule sets, listing creation and the activation transition."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    types,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    READER_HOST,
    SECOND_COMPLIANCE_OFFICER,
)


def test_jurisdiction_rule_round_trips_all_nine_policy_inputs(api):
    """Create, read and list a rule set and get the same nine policy values back.

    The read is taken by a different role than the writer, so the round trip also
    shows the rule set is public reference data rather than the author's private
    row.

    PRD: "Publication also fixes `min_stay_nights`, which must be at least 1; `max_occupancy_cap`, the statutory head-count ceiling, also at least 1; the boolean flags `events_prohibited`, `registration_required`, `indoor_camera_allowed`, `indoor_audio_allowed` and `sensor_notice_required`; and `noise_threshold_db`, a decibel level that must be greater than zero."
    PRD: "A rule set is immutable: there is no way to amend one, it carries neither `updated_at` nor `version`, and rule sets can be looked up individually or listed with an optional `jurisdiction_code` filter."

    Design: Corner/endpoints/jurisdiction_rule_create_and_read_round_trip
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)

    created = validate_success(
        api.create_jurisdiction_rule(
            COMPLIANCE_OFFICER, **factories.jurisdiction_rule_payload()
        ),
        expected_status=201,
    )
    read_back = validate_success(
        api.get_jurisdiction_rule(created["id"], READER_HOST), expected_status=200
    )

    assert read_back["id"] == created["id"], (
        "the read must address the same rule set that was created"
    )
    assertions.assert_fields(
        read_back,
        "jurisdiction_rule",
        jurisdiction_code="US-CA-SFO",
        min_stay_nights=2,
        max_occupancy_cap=8,
        noise_threshold_db=70,
        events_prohibited=False,
        registration_required=False,
        indoor_camera_allowed=True,
        indoor_audio_allowed=False,
        sensor_notice_required=True,
    )
    assert "version" not in read_back, (
        "a jurisdiction rule set carries no version field, got {0!r}".format(
            read_back.get("version")
        )
    )
    types.assert_is_jurisdiction_rule(read_back)

    assertions.assert_page(
        api.list_jurisdiction_rules(READER_HOST, jurisdiction_code="US-CA-SFO"),
        total_count=1,
    )


def test_jurisdiction_rule_carries_neither_updated_at_nor_version(api):
    """A rule set is one of the three write-once entities of the contract.

    A second locality is published with a stricter policy set so the assertion is
    not reading defaults that happen to coincide with the canonical rule set.

    PRD: "A jurisdiction rule set, a claim-evidence artifact and a settlement-allocation line each carry only `id` and `created_at`: both `updated_at` and `version` are absent from their representations, because all three are immutable once written."
    PRD: "A rule set is immutable: there is no way to amend one, it carries neither `updated_at` nor `version`, and rule sets can be looked up individually or listed with an optional `jurisdiction_code` filter."

    Design: Corner/entities/jurisdiction_rule_is_immutable_with_no_version_field
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)

    rule = validate_success(
        api.create_jurisdiction_rule(
            COMPLIANCE_OFFICER,
            **factories.jurisdiction_rule_payload(
                jurisdiction_code="US-WA-SEA",
                min_stay_nights=3,
                max_occupancy_cap=6,
                events_prohibited=True,
                registration_required=True,
                indoor_camera_allowed=False,
                indoor_audio_allowed=False,
                sensor_notice_required=True,
                noise_threshold_db=65,
            )
        ),
        expected_status=201,
    )

    types.assert_write_once_properties(rule, "jurisdiction_rule")
    assertions.assert_fields(
        rule,
        "jurisdiction_rule",
        jurisdiction_code="US-WA-SEA",
        min_stay_nights=3,
        max_occupancy_cap=6,
        events_prohibited=True,
        registration_required=True,
        indoor_camera_allowed=False,
        indoor_audio_allowed=False,
        sensor_notice_required=True,
        noise_threshold_db=65,
    )

    read_back = validate_success(
        api.get_jurisdiction_rule(rule["id"], READER_HOST), expected_status=200
    )
    types.assert_write_once_properties(read_back, "jurisdiction_rule")


def test_second_rule_for_a_taken_jurisdiction_code_is_refused(api):
    """The stored policy survives a colliding publication untouched.

    Every policy value on the second attempt differs from the first, so nothing
    but the code itself can be the cause of the rejection — and nothing from the
    second body may leak onto the stored row.

    PRD: "The code must not already exist; a collision is refused with `ERR_JURISDICTION_CODE_TAKEN`."

    Design: Corner/errors/jurisdiction_code_taken_rejected
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    first = fixtures.create_jurisdiction_rule(api)

    response = api.create_jurisdiction_rule(
        SECOND_COMPLIANCE_OFFICER,
        **factories.jurisdiction_rule_payload(
            jurisdiction_code="US-CA-SFO",
            min_stay_nights=7,
            max_occupancy_cap=2,
            events_prohibited=True,
            registration_required=True,
            indoor_camera_allowed=False,
            indoor_audio_allowed=False,
            sensor_notice_required=False,
            noise_threshold_db=55,
        )
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_CODE_TAKEN, expected_status=409)

    stored = validate_success(
        api.get_jurisdiction_rule(first["id"], READER_HOST), expected_status=200
    )
    assertions.assert_fields(
        stored,
        "jurisdiction_rule",
        min_stay_nights=2,
        noise_threshold_db=70,
        registration_required=False,
    )
    assertions.assert_page(
        api.list_jurisdiction_rules(READER_HOST, jurisdiction_code="US-CA-SFO"),
        total_count=1,
    )


def test_draft_listing_reports_its_stored_configuration_and_empty_postures(api):
    """A freshly created listing echoes its inputs and derives three postures.

    Nothing has been installed at the listing and no insurance has been
    published for it, which is exactly the pair of vacuous cases the two
    aggregates resolve in opposite directions.

    PRD: "A new listing lands in `DRAFT` with `suspension_reason` null."
    PRD: "Otherwise the posture is `COMPLIANT`, and that includes the vacuous case of a listing with no devices at all: an unmonitored listing is deliberately bookable."
    PRD: "When the available count is zero the posture is `UNPROTECTED`; when the available count is below the visible count the posture is `REDUCED`; otherwise it is `FULL`."
    PRD: "`open_reservation_count` is the number of reservations of this listing whose `stay_state` is `REQUESTED`, `CONFIRMED` or `IN_STAY`."

    Design: Corner/entities/property_retrieval_returns_stored_listing_configuration
    """
    cast = fixtures.setup_waiver_listing(
        api, host_email="cornerhost1@stays.test", activate=False
    )

    listing = validate_success(
        api.get_property(cast.property_id, cast.host_headers), expected_status=200
    )

    types.assert_is_property(listing)
    assertions.assert_fields(
        listing,
        "property",
        host_id=cast.host_id,
        jurisdiction_rule_id=cast.jurisdiction_rule_id,
        nightly_rate_cents=30000,
        protection_product="WAIVER",
        waiver_nightly_fee_cents=3000,
        deposit_amount_cents=0,
        claim_ceiling_cents=500000,
        event_policy="EVENTS_ALLOWED",
        turnover_buffer_nights=0,
        listing_state="DRAFT",
        suspension_reason=None,
        sensor_compliance_state="COMPLIANT",
        coverage_posture="UNPROTECTED",
        open_reservation_count=0,
        open_claim_count=0,
        registration_number=None,
        version=1,
    )


def test_listing_omitting_its_optionals_takes_the_declared_defaults(api):
    """A body without turnover_buffer_nights or registration_number still lands cleanly.

    The buffer must come back as the integer 0 rather than null, because a later
    calendar comparison arithmetic on it, and the listing must begin in DRAFT
    without any suspension recorded against it.

    PRD: "An optional `turnover_buffer_nights`, defaulting to 0 and never negative, declares a mandatory cleaning gap between two consecutive bookings of the listing."
    PRD: "A new listing lands in `DRAFT` with `suspension_reason` null."

    Design: Corner/entities/property_omitted_optionals_take_declared_defaults
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    rule = fixtures.create_jurisdiction_rule(api)
    host = fixtures.create_host(api, email="cornerhost3@stays.test")
    host_headers = fixtures.make_host_headers(host["id"])

    payload = factories.deposit_property_payload(host["id"], rule["id"])
    payload.pop("turnover_buffer_nights")

    listing = validate_success(
        api.create_property(host_headers, **payload), expected_status=201
    )

    assertions.assert_fields(
        listing,
        "property",
        turnover_buffer_nights=0,
        registration_number=None,
        listing_state="DRAFT",
        suspension_reason=None,
        deposit_amount_cents=50000,
        waiver_nightly_fee_cents=0,
    )


def test_listing_without_a_nightly_rate_is_malformed_and_persists_nothing(api):
    """nightly_rate_cents has no default, so omitting it is a shape failure.

    The listing collection is read back afterwards to prove the refusal was total
    rather than a partially written row.

    PRD: "Every required body field present with the declared type, every enum field holding a declared value, every integer inside its declared bound, and `limit`/`offset` inside their permitted ranges — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/property_create_missing_required_nightly_rate_rejected
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    rule = fixtures.create_jurisdiction_rule(api)
    host = fixtures.create_host(api, email="cornerhost2@stays.test")
    host_headers = fixtures.make_host_headers(host["id"])

    payload = factories.waiver_property_payload(host["id"], rule["id"])
    payload.pop("nightly_rate_cents")
    payload.pop("turnover_buffer_nights")

    validate_error(
        api.create_property(host_headers, **payload),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    assertions.assert_page(
        api.list_properties(host_headers, host_id=host["id"]), total_count=0
    )


def test_undeclared_protection_product_is_a_shape_failure_not_a_fiscal_one(api):
    """An enum value outside the declared pair never reaches the product-coherence rule.

    The body would also have failed the fiscal coherence check had it been
    admitted, so the error identifier is what distinguishes the two rules: shape
    is checked third in the precedence order and coherence very nearly last.

    PRD: "`protection_product` is either `DEPOSIT` or `WAIVER`, and exactly one of the two accompanying money fields may be populated."
    PRD: "Every required body field present with the declared type, every enum field holding a declared value, every integer inside its declared bound, and `limit`/`offset` inside their permitted ranges — `ERR_INVALID_REQUEST`."
    PRD: "This is a fiscal check and is therefore evaluated after every structural, existence and ownership check on the same request."

    Design: Corner/entities/property_invalid_enum_protection_product_rejected
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    rule = fixtures.create_jurisdiction_rule(api)
    host = fixtures.create_host(api, email="cornerhost4@stays.test")
    host_headers = fixtures.make_host_headers(host["id"])

    payload = factories.waiver_property_payload(
        host["id"], rule["id"], protection_product="INSURANCE"
    )
    payload.pop("turnover_buffer_nights")

    validate_error(
        api.create_property(host_headers, **payload),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    assertions.assert_page(
        api.list_properties(host_headers, host_id=host["id"]), total_count=0
    )


def test_listing_naming_an_unstored_rule_set_reports_the_rule_not_found(api):
    """The two foreign keys resolve in declaration order, host first.

    The acting host does exist, so if the resolution order were reversed the
    refusal would have named the host instead — the identifier is the only thing
    that shows which side was checked.

    PRD: "Creating a listing therefore resolves `host_id` before `jurisdiction_rule_id`; creating a blocklist entry resolves `guest_id`, then `property_id`, then `host_id`, then `supersedes_entry_id`, with an unresolvable supersession pointer reported as `ERR_BLOCKLIST_ENTRY_NOT_FOUND`."
    PRD: "Every foreign-key identifier in the request body resolves to a stored row, checked in the order the fields are declared on the entity, each with its own not-found error."

    Design: Corner/entities/property_create_with_unknown_jurisdiction_rule_not_found
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    host = fixtures.create_host(api, email="cornerhost5@stays.test")
    host_headers = fixtures.make_host_headers(host["id"])

    payload = factories.waiver_property_payload(host["id"], NON_EXISTENT_UUID)
    payload.pop("turnover_buffer_nights")

    validate_error(
        api.create_property(host_headers, **payload),
        ApiErrorId.ERR_JURISDICTION_RULE_NOT_FOUND,
        expected_status=404,
    )

    assertions.assert_page(
        api.list_properties(host_headers, host_id=host["id"]), total_count=0
    )


def test_first_activation_moves_a_draft_listing_to_active(api):
    """Activation is the host's own move and bumps the listing's version once.

    The bound rule set does not require a registration number and no device has
    been installed, so the two other preconditions of the first activation are
    already satisfied and only the transition itself is under test.

    PRD: "The first activation moves `listing_state` from `DRAFT` to `ACTIVE`, and demands that the acting host owns the listing, that `sensor_compliance_state` reads `COMPLIANT`, and that `registration_number` is present and non-empty whenever the bound jurisdiction has `registration_required` set true — a missing registration number in a registration-required jurisdiction is refused with `ERR_REGISTRATION_REQUIRED`."
    PRD: "Either transition clears `suspension_reason` back to null and increases the listing's `version` by 1."

    Design: Corner/state_machines/property_activate_moves_draft_listing_to_active
    """
    cast = fixtures.setup_waiver_listing(
        api, host_email="smhost1@stays.test", activate=False
    )
    before = validate_success(
        api.get_property(cast.property_id, cast.host_headers), expected_status=200
    )
    assertions.assert_version(before, 1, "property")

    activated = validate_success(
        api.activate_property(cast.property_id, cast.host_headers), expected_status=200
    )

    assertions.assert_fields(
        activated,
        "property",
        listing_state="ACTIVE",
        suspension_reason=None,
        sensor_compliance_state="COMPLIANT",
    )
    assertions.assert_version_advanced_by(before, activated, 1, "property")

    stored = validate_success(
        api.get_property(cast.property_id, cast.host_headers), expected_status=200
    )
    assertions.assert_fields(stored, "property", listing_state="ACTIVE", version=2)


def test_activation_without_a_registration_number_is_refused_where_it_is_required(api):
    """A registration-required locality blocks the very first activation.

    The listing is otherwise activatable — the host owns it and its sensor
    posture is COMPLIANT — so the missing registration number is the only
    unsatisfied precondition, and the listing must stay exactly where it was.

    PRD: "The first activation moves `listing_state` from `DRAFT` to `ACTIVE`, and demands that the acting host owns the listing, that `sensor_compliance_state` reads `COMPLIANT`, and that `registration_number` is present and non-empty whenever the bound jurisdiction has `registration_required` set true — a missing registration number in a registration-required jurisdiction is refused with `ERR_REGISTRATION_REQUIRED`."

    Design: Corner/state_machines/property_activate_without_registration_number_rejected
    """
    cast = fixtures.setup_waiver_listing(
        api,
        host_email="smhost2@stays.test",
        activate=False,
        rule_overrides={
            "jurisdiction_code": "US-WA-SEA",
            "min_stay_nights": 3,
            "max_occupancy_cap": 6,
            "events_prohibited": True,
            "registration_required": True,
            "indoor_camera_allowed": False,
            "indoor_audio_allowed": False,
            "sensor_notice_required": True,
            "noise_threshold_db": 65,
        },
    )
    assert cast.property["registration_number"] is None, (
        "the listing under test must carry no registration number"
    )

    validate_error(
        api.activate_property(cast.property_id, cast.host_headers),
        ApiErrorId.ERR_REGISTRATION_REQUIRED,
        expected_status=422,
    )

    stored = validate_success(
        api.get_property(cast.property_id, cast.host_headers), expected_status=200
    )
    assertions.assert_fields(stored, "property", listing_state="DRAFT", version=1)


def test_activating_an_already_active_listing_reports_an_invalid_transition(api):
    """ACTIVE is not terminal, so the second activation is an undeclared edge.

    The distinction matters because the terminality check runs before the
    declared-transition check: a state machine with no terminal state at all can
    never report the terminal error, and the version must not move either.

    PRD: "A listing's `listing_state` runs `DRAFT`, `ACTIVE`, `SUSPENDED` with no terminal state at all."
    PRD: "The resource sits in a non-terminal state from which the requested transition exists — `ERR_INVALID_STATE`."

    Design: Corner/state_machines/property_activate_from_active_returns_invalid_state
    """
    cast = fixtures.setup_waiver_listing(
        api, host_email="smhost4@stays.test", activate=False
    )
    first = validate_success(
        api.activate_property(cast.property_id, cast.host_headers), expected_status=200
    )
    assertions.assert_fields(first, "property", listing_state="ACTIVE", version=2)

    validate_error(
        api.activate_property(cast.property_id, cast.host_headers),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    stored = validate_success(
        api.get_property(cast.property_id, cast.host_headers), expected_status=200
    )
    assertions.assert_fields(stored, "property", listing_state="ACTIVE", version=2)


def test_protection_product_and_its_money_fields_must_agree_in_both_directions(api):
    """A deposit listing may not also charge a waiver fee, and the mirror fails too.

    Both halves of the coherence rule are exercised on the same host, and the
    listing collection is read back to show that neither malformed configuration
    was stored.

    PRD: "On a `DEPOSIT` listing, `deposit_amount_cents` must be greater than zero and `waiver_nightly_fee_cents` must be exactly zero."
    PRD: "On a `WAIVER` listing the reverse holds: `waiver_nightly_fee_cents` must be greater than zero and `deposit_amount_cents` must be exactly zero."
    PRD: "Either field may otherwise be zero or above, but any combination that contradicts the declared product is refused with `ERR_PRODUCT_CONFIG_INVALID`."

    Design: Corner/errors/deposit_product_config_invalid_rejected
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    rule = fixtures.create_jurisdiction_rule(api)
    host = fixtures.create_host(api, email="errhost1@stays.test")
    host_headers = fixtures.make_host_headers(host["id"])

    deposit_body = factories.deposit_property_payload(
        host["id"],
        rule["id"],
        address_line="3 Mixed Product Road",
        waiver_nightly_fee_cents=3000,
    )
    deposit_body.pop("turnover_buffer_nights")
    validate_error(
        api.create_property(host_headers, **deposit_body),
        ApiErrorId.ERR_PRODUCT_CONFIG_INVALID,
        expected_status=422,
    )

    waiver_body = factories.waiver_property_payload(
        host["id"],
        rule["id"],
        address_line="3 Mixed Product Road",
        deposit_amount_cents=50000,
        waiver_nightly_fee_cents=3000,
    )
    waiver_body.pop("turnover_buffer_nights")
    validate_error(
        api.create_property(host_headers, **waiver_body),
        ApiErrorId.ERR_PRODUCT_CONFIG_INVALID,
        expected_status=422,
    )

    assertions.assert_page(
        api.list_properties(host_headers, host_id=host["id"]), total_count=0
    )
