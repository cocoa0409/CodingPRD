"""Refusals whose identity is the point: which code, and which rung chose it.

Path existence outranks every state check and each resource owns its own
not-found identifier; the remedy safety lock is ordinal rather than an equality
test; severity decides whether a regulatory filing is possible at all; and the
active-consent key is policed on the supersession pointer too.
"""

import pytest

from test_helpers import (
    ADJUDICATOR_1_ID,
    ApiErrorId,
    TEST_USERS,
    add_assessment,
    add_claim,
    adjudicate_payload,
    assert_same_instant,
    assert_thermal_event,
    consent_payload,
    create_campaign,
    ingest_snapshot,
    list_campaign_consents,
    make_adjudicator_headers,
    read_campaign,
    read_center,
    read_claim,
    read_event,
    read_pack,
    read_program,
    read_vehicle,
    regulatory_notification_payload,
    release_campaign,
    report_thermal_event,
    setup_base_world,
    setup_program,
    setup_released_campaign_world,
    tender_payload,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["program_admin_headers"]
TECHNICIAN_HEADERS = TEST_USERS["technician_headers"]
LIAISON_HEADERS = TEST_USERS["liaison_headers"]
LAB_HEADERS = TEST_USERS["lab_headers"]


class TestUnknownPathIdentifiers:
    """Six probes at an empty surface, each answered by its own resource's code."""

    def test_each_missing_row_reports_its_own_not_found_and_outranks_state(self, api):
        """A nested listing reports the parent's code, and an action route 404s first.

        PRD 2.7: "6. Existence of every path-parameter resource, left to right."

        PRD 2.7: "34. Shipment status `DRAFT` for a tender and `TENDERED` for a receipt
        — `ERR_SHIPMENT_NOT_TENDERED`."

        PRD 5: "Every rejection returns the error envelope of section 2.2 with one of
        the identifiers below in its `error_id` field. When more than one rule is
        violated by a single request, the identifier returned is the one whose position
        in the precedence ladder of section 2.7 is earliest."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error." / "The `message` provides a human-readable explanation of
        what went wrong."

        Design: Corner/errors/unknown_path_ids_each_return_their_own_not_found_code
        """
        # A programme exists so the surface is live; none of the probed rows do.
        setup_program(api)

        validate_error(
            api.get_battery_pack("pack_missing", ADMIN_HEADERS),
            ApiErrorId.ERR_PACK_NOT_FOUND.value,
            expected_status=404,
        )

        # The nested route resolves its parent first: no empty page is admissible.
        validate_error(
            api.list_battery_modules("pack_missing", ADMIN_HEADERS),
            ApiErrorId.ERR_PACK_NOT_FOUND.value,
            expected_status=404,
        )

        validate_error(
            api.get_shipment("ship_missing", ADMIN_HEADERS),
            ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value,
            expected_status=404,
        )

        # Rung 6 settles this before the rung-34 shipment-status check can look.
        validate_error(
            api.tender_shipment(
                "ship_missing", tender_payload("CAR-0001"), TECHNICIAN_HEADERS
            ),
            ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value,
            expected_status=404,
        )

        validate_error(
            api.get_thermal_event("evt_missing", LIAISON_HEADERS),
            ApiErrorId.ERR_EVENT_NOT_FOUND.value,
            expected_status=404,
        )

        validate_error(
            api.get_dispute("dsp_missing", LAB_HEADERS),
            ApiErrorId.ERR_DISPUTE_NOT_FOUND.value,
            expected_status=404,
        )


# One clean cell-delta window: three fresh rows at 56.000 kWh and 20 °C, the newest
# carrying a 300 mV spread against the programme's 250 mV threshold.
CELL_DELTA_ROWS = [
    ("2026-07-20T00:00:00Z", 71000, 40),
    ("2026-07-22T00:00:00Z", 71200, 40),
    ("2026-07-24T00:00:00Z", 71400, 300),
]


class TestOrdinalRemedyLock:
    """A CELL_DELTA pack recommendation refuses both weaker remedies, yet admits denial."""

    def test_two_downgrades_are_refused_and_the_denial_is_accepted(self, api):
        """The lock is ordinal, so DENIED — ordinally nothing — is still available.

        PRD 3.5: "Otherwise, if the assessment's `max_cell_delta_mv` is at or above the
        program's `cell_delta_pack_threshold_mv`, the recommendation is
        `PACK_REPLACEMENT` with basis `CELL_DELTA`."

        PRD 3.4: "the newest row in it supplies both `assessed_odometer_miles` and the
        assessment's own `max_cell_delta_mv`."

        PRD 3.5: "remedies have an ordinal strength, with `SOFTWARE_REMEDIATION` weaker
        than `MODULE_REPLACEMENT`, which is weaker than `PACK_REPLACEMENT`, and an
        adjudicator may not approve anything weaker than a `PACK_REPLACEMENT`
        recommendation whose `recommendation_basis` is `THERMAL_HISTORY` or
        `CELL_DELTA`. Attempting to is refused with `ERR_REMEDY_OVERRIDE_FORBIDDEN`.
        Denial is always available, whatever the recommendation said."

        PRD 3.5: "**Denying the claim** moves it from `SUBMITTED` to `DENIED` and
        requires an `override_justification` to be present, because a denial is by
        definition a departure from a remedy recommendation. It sets `denial_reason` to
        `ADJUDICATOR_DECISION` and zeroes the money ... and the program's
        `accrued_liability_cents` is left entirely unchanged."

        Design: Corner/errors/adjudicator_cannot_weaken_a_cell_delta_pack_recommendation
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000531"},
            pack_overrides={"serial_number": "PK-C331"},
            snapshots=None,
        )
        assert world["program"]["cell_delta_pack_threshold_mv"] == 250
        for captured_at, odometer, delta in CELL_DELTA_ROWS:
            ingest_snapshot(
                api,
                world["vehicle_id"],
                captured_at,
                odometer,
                56.000,
                max_cell_delta_mv=delta,
            )

        assessment = add_assessment(api, world, module_fault_positions=[3, 7])
        assert assessment["diagnostic_validity"] == "VALID"
        assert assessment["window_snapshot_count"] == 3
        # The newest window row, not the window's mean of 126.7 mV.
        assert assessment["max_cell_delta_mv"] == 300
        assert assessment["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert assessment["qualifies_for_claim"] is True

        pack = read_pack(api, world["pack_id"])
        assert pack["faulted_module_count"] == 2
        assert pack["module_count"] == 16

        # Only 2 of 16 modules are faulted, so rung 3 of the ladder would have said
        # MODULE_REPLACEMENT; the cell spread pre-empts it at rung 2.
        claim = add_claim(api, world)
        assert claim["adjudication_status"] == "SUBMITTED"
        assert claim["recommended_remedy"] == "PACK_REPLACEMENT"
        assert claim["recommendation_basis"] == "CELL_DELTA"

        campaign = create_campaign(
            api,
            campaign_code="CMP-OVR-01",
            target_defect="CHARGING",
            software_version="bms-4.2.1",
            applies_to_pack_type="ANY",
            applies_to_model_code="MX-90",
        )
        released = release_campaign(api, campaign["id"], "FIELD")
        assert released["status"] == "FIELD_RELEASE"

        adjudicator = make_adjudicator_headers(ADJUDICATOR_1_ID)

        # One rung weaker, with the justification the departure rule demands present,
        # so nothing but the safety lock can be doing the refusing.
        validate_error(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload("MODULE_REPLACEMENT", override_justification="cheaper"),
                adjudicator,
            ),
            ApiErrorId.ERR_REMEDY_OVERRIDE_FORBIDDEN.value,
            expected_status=409,
        )
        after_first = read_claim(api, world["claim_id"])
        assert after_first["adjudication_status"] == "SUBMITTED"
        assert after_first["adjudicated_by_user_id"] is None

        # Two rungs weaker, naming a genuinely released campaign that does target this
        # vehicle's model: still refused, and the campaign is not recorded.
        validate_error(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload(
                    "SOFTWARE_REMEDIATION",
                    linked_campaign_id=campaign["id"],
                    override_justification="owner would rather take the flash",
                ),
                adjudicator,
            ),
            ApiErrorId.ERR_REMEDY_OVERRIDE_FORBIDDEN.value,
            expected_status=409,
        )
        after_second = read_claim(api, world["claim_id"])
        assert after_second["adjudication_status"] == "SUBMITTED"
        assert after_second["linked_campaign_id"] is None

        denied = validate_success(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload(
                    "DENIED",
                    override_justification="owner-induced abuse",
                    decision_note="owner-induced abuse",
                ),
                adjudicator,
            )
        )
        assert denied["adjudication_status"] == "DENIED"
        assert denied["denial_reason"] == "ADJUDICATOR_DECISION"
        assert denied["remedy_cost_cents"] == 0
        assert denied["owner_share_cents"] == 0
        assert denied["oem_share_cents"] == 0
        assert denied["admin_fee_cents"] == 0
        assert denied["oem_total_cents"] == 0
        assert denied["proration_factor"] == pytest.approx(0.0, abs=0.0001)
        assert denied["adjudicated_by_user_id"] == ADJUDICATOR_1_ID

        # A denial accrues nothing, and no refusal accrued anything either.
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 0


class TestS1EventHasNoRegulatoryDimension:
    """Severity alone decides whether a filing is possible at all."""

    def test_filing_an_s1_event_is_refused_and_moves_no_counter(self, api):
        """A null deadline is not a missed one: the filing is refused, never filed late.

        PRD 2.7: "25. Notification status `PENDING` for a regulatory filing —
        `ERR_NOTIFICATION_ALREADY_FILED`."

        PRD 3.7: "For `S4` the `notification_deadline_at` is `detected_at` plus
        twenty-four hours; for `S3` it is `detected_at` plus seventy-two hours; and for
        `S1` or `S2` there is no deadline at all, so `notification_deadline_at` stays
        null. Correspondingly `notification_status` starts at `PENDING` when a deadline
        exists and at `NOT_REQUIRED` when it does not."

        PRD 3.7: "`notification_status` must be `PENDING`, or the filing is refused with
        `ERR_NOTIFICATION_ALREADY_FILED` — which is also what a second filing attempt
        receives, and what a filing against an `S1` or `S2` event whose status is
        `NOT_REQUIRED` receives, since that status is terminal on this dimension."

        PRD 3.7: "An `S1` or `S2` report fires none of this: the pack stays
        `IN_SERVICE`, the vehicle stays `ACTIVE`, consents are untouched, and
        `affected_module_positions` records the implicated positions without changing any
        module's status or flag."

        PRD 3.7: "Creation sets `containment_status` to `DETECTED`,
        `containment_steps_completed` to 0 and `event_status` to `OPEN`."

        Design: Corner/errors/s1_event_has_no_regulatory_filing_and_returns_notification_not_required
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000541"},
            pack_overrides={"serial_number": "PK-C341"},
            snapshots=None,
        )
        event = report_thermal_event(
            api,
            world,
            severity="S1",
            detected_at="2026-07-25T00:00:00Z",
            affected_module_positions=[5],
            source="TELEMATICS",
        )
        assert_thermal_event(event)
        assert event["notification_status"] == "NOT_REQUIRED"
        assert event["notification_deadline_at"] is None

        # The status is NOT_REQUIRED rather than PENDING, which is the rung-25 guard,
        # and the PRD names that guard's identifier for exactly this S1 case.
        validate_error(
            api.file_regulatory_notification(
                event["id"],
                regulatory_notification_payload(world["center_id"], "REG-S1-1"),
                LIAISON_HEADERS,
            ),
            ApiErrorId.ERR_NOTIFICATION_ALREADY_FILED.value,
            expected_status=409,
        )

        refused = read_event(api, event["id"])
        assert refused["notification_status"] == "NOT_REQUIRED"
        assert refused["notification_deadline_at"] is None
        assert refused["notification_filed_at"] is None
        assert refused["regulator_reference"] is None
        assert refused["reporting_service_center_id"] is None
        # The containment dimension advances independently and was never touched.
        assert refused["containment_status"] == "DETECTED"
        assert refused["containment_steps_completed"] == 0
        assert refused["event_status"] == "OPEN"

        center = read_center(api, world["center_id"])
        assert center["late_notification_count"] == 0
        assert center["compliance_score"] == 100
        assert center["status"] == "ACTIVE"

        vehicle = read_vehicle(api, world["vehicle_id"])
        assert vehicle["status"] == "ACTIVE"
        assert vehicle["warranty_hold"] is False
        pack = read_pack(api, world["pack_id"])
        assert pack["status"] == "IN_SERVICE"
        assert pack["damaged_defective"] is False


class TestDuplicateActiveConsent:
    """The active-consent key is enforced twice: bare, and through the pointer."""

    def test_a_pending_predecessor_cannot_be_duplicated_or_superseded(self, api):
        """Naming the still-open predecessor is the same violation as filing blind.

        PRD 3.8: "Finally no consent with `consent_status` `PENDING` or `GRANTED` may
        already exist for the same campaign-and-vehicle pair, and any supplied
        `superseded_consent_id` must point at a consent for that same pair whose
        `consent_status` is `DECLINED` or `EXPIRED`; a violation of either half is
        refused with `ERR_DUPLICATE_ACTIVE_CONSENT`."

        PRD 3.8: "Consents are created two ways. A campaign release creates the first
        round in bulk, and an approved software claim cascade-creates one if none exists
        for its campaign-and-vehicle pair."

        PRD 3.8: "An accepted solicitation creates the consent in `PENDING`, sets
        `expires_at` to its own `created_at` plus fourteen days, and sets
        `solicitation_round` to the superseded consent's `solicitation_round` plus one
        when one was named and to 1 otherwise. It raises the campaign's
        `solicited_consent_count` and `open_consent_count` each by one, and raises the
        campaign's `version` by one."

        Design: Corner/errors/duplicate_active_consent_for_the_same_campaign_vehicle_pair_is_rejected
        """
        world = setup_released_campaign_world(
            api,
            release_scope="FIELD",
            campaign_overrides={
                "campaign_code": "CMP-DUPC-01",
                "target_defect": "CHARGING",
                "software_version": "bms-4.2.1",
                "applies_to_pack_type": "ANY",
                "applies_to_model_code": "MX-90",
            },
            vehicle_overrides={"vin": "5YJ3E1EA7KF000551"},
            pack_overrides={"serial_number": "PK-C351"},
            snapshots=None,
        )
        campaign = read_campaign(api, world["campaign_id"])
        assert campaign["status"] == "FIELD_RELEASE"
        assert campaign["release_scope"] == "FIELD"
        assert campaign["solicited_consent_count"] == 1
        assert campaign["open_consent_count"] == 1
        assert campaign["applied_count"] == 0
        campaign_version = campaign["version"]

        # The release itself armed the conflict: one PENDING first-round consent.
        predecessor = world["consent"]
        assert predecessor["consent_status"] == "PENDING"
        assert predecessor["solicitation_round"] == 1
        assert predecessor["superseded_consent_id"] is None

        validate_error(
            api.create_consent(
                consent_payload(
                    world["campaign_id"], world["vehicle_id"], campaign_version
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_ACTIVE_CONSENT.value,
            expected_status=409,
        )

        # A predecessor must be DECLINED or EXPIRED; a PENDING one is the same offence.
        validate_error(
            api.create_consent(
                consent_payload(
                    world["campaign_id"],
                    world["vehicle_id"],
                    campaign_version,
                    superseded_consent_id=predecessor["id"],
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_ACTIVE_CONSENT.value,
            expected_status=409,
        )

        rows, meta = list_campaign_consents(api, world["campaign_id"])
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        surviving = rows[0]
        assert surviving["id"] == predecessor["id"]
        assert surviving["consent_status"] == "PENDING"
        assert surviving["solicitation_round"] == 1
        assert surviving["superseded_consent_id"] is None
        assert_same_instant(
            surviving["expires_at"], "2026-08-15T00:00:00Z", "consent.expires_at"
        )
        assert surviving["decision_at"] is None
        assert surviving["applied_at"] is None

        # Two refusals bumped no counter and no version.
        unchanged = read_campaign(api, world["campaign_id"])
        assert unchanged["solicited_consent_count"] == 1
        assert unchanged["open_consent_count"] == 1
        assert unchanged["applied_count"] == 0
        assert unchanged["status"] == "FIELD_RELEASE"
        assert unchanged["version"] == campaign_version
