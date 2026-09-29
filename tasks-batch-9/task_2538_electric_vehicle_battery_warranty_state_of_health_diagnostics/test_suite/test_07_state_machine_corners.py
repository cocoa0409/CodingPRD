"""Lifecycle edges taken one at a time: openings, guards and terminal lockdowns.

Each test here pins one transition or one refusal, and every refusal is proved
inert — the counters, the pointers and the ledger a rejected call might have
touched are all re-read afterwards.
"""

import pytest

from test_helpers import (
    ADJUDICATOR_1_ID,
    ADJUDICATOR_2_ID,
    ApiErrorId,
    add_assessment,
    adjudicate_payload,
    apply_update_payload,
    assert_event_status_join,
    assert_module_statuses,
    assert_remediation_campaign,
    assert_remediation_consent,
    assert_same_instant,
    assert_soh_assessment,
    assert_thermal_event,
    claim_payload,
    close_payload,
    create_campaign,
    dispute_payload,
    fulfil_payload,
    list_campaign_consents,
    list_claims,
    list_modules,
    make_adjudicator_headers,
    make_technician_headers,
    read_assessment,
    read_campaign,
    read_center,
    read_claim,
    read_consent,
    read_event,
    read_pack,
    read_program,
    read_vehicle,
    read_vehicle_version,
    regulatory_notification_payload,
    release_payload,
    report_thermal_event,
    request_info_payload,
    resubmit_payload,
    setup_base_world,
    setup_center,
    setup_installed_pack,
    setup_released_campaign_world,
    setup_submitted_claim_world,
    setup_vehicle,
    validate_error,
    validate_success,
)


class TestThermalEventInitialDimensions:
    """A mild event opens one live dimension and one already-settled one."""

    def test_an_s1_report_opens_containment_live_and_notification_not_required(self, api):
        """DETECTED and NOT_REQUIRED together, with no cascade anywhere.

        PRD 3.7: "Creation sets `containment_status` to `DETECTED`,
        `containment_steps_completed` to 0 and `event_status` to `OPEN`, and it fixes
        the notification obligation immediately. ... for `S1` or `S2` there is no
        deadline at all, so `notification_deadline_at` stays null. Correspondingly
        `notification_status` starts at `PENDING` when a deadline exists and at
        `NOT_REQUIRED` when it does not. `notification_filed_at`,
        `regulator_reference` and `reporting_service_center_id` all start null."

        PRD 3.7: "An `S1` or `S2` report fires none of this: the pack stays
        `IN_SERVICE`, the vehicle stays `ACTIVE`, consents are untouched, and
        `affected_module_positions` records the implicated positions without changing
        any module's status or flag."

        Design: Corner/state_machines/thermal_event_s1_creation_sets_both_initial_dimensions
        """
        world = setup_base_world(api, snapshots=None)

        event = report_thermal_event(
            api,
            world,
            severity="S1",
            detected_at="2026-07-31T12:00:00Z",
            affected_module_positions=[4],
            source="TELEMATICS",
        )
        assert_thermal_event(event)
        assert event["severity"] == "S1"
        assert event["containment_status"] == "DETECTED"
        assert event["containment_steps_completed"] == 0
        assert event["event_status"] == "OPEN"
        assert_same_instant(event["detected_at"], "2026-07-31T12:00:00Z", "detected_at")

        # The regulatory dimension is settled at birth for a mild event.
        assert event["notification_status"] == "NOT_REQUIRED"
        assert event["notification_deadline_at"] is None
        assert event["notification_filed_at"] is None
        assert event["regulator_reference"] is None
        assert event["reporting_service_center_id"] is None
        assert_event_status_join(event)

        # None of the severe-event cascade ran.
        pack = read_pack(api, world["pack_id"])
        assert pack["status"] == "IN_SERVICE"
        assert pack["damaged_defective"] is False

        vehicle = read_vehicle(api, world["vehicle_id"])
        assert vehicle["status"] == "ACTIVE"
        assert vehicle["warranty_hold"] is False

        modules, _ = list_modules(api, world["pack_id"], limit=100)
        assert_module_statuses(modules, {4: "HEALTHY"})
        implicated = {row["position_index"]: row for row in modules}[4]
        assert implicated["thermal_runaway_flag"] is False


class TestLimitedReleaseFork:
    """The limited branch needs a pilot list, and it honours it."""

    def test_an_empty_pilot_list_is_refused_and_a_named_region_solicits_only_itself(
        self, api
    ):
        """One eligible car in the pilot region, one identical car outside it.

        PRD 3.8: "A `LIMITED` release moves the campaign to `LIMITED_RELEASE`, records
        `release_scope` as `LIMITED`, and intersects the core filter with the pilot
        regions: the vehicle's `region_code` must be a member of `pilot_region_codes`.
        It also requires `pilot_region_codes` to be non-empty, since a limited release
        with no pilot region would solicit nobody; an empty list is refused with
        `ERR_INVALID_REQUEST`."

        PRD 3.8: "A new campaign starts in `status` `DRAFT` with a null `release_scope`
        and all three counters — `solicited_consent_count`, `open_consent_count` and
        `applied_count` — at zero."

        PRD 3.8: "both create one `PENDING` consent per eligible vehicle in ascending
        vehicle `created_at` order, then set both `solicited_consent_count` and
        `open_consent_count` to the number of consents created."

        Design: Corner/state_machines/limited_release_requires_pilot_regions_then_solicits_only_pilot_vehicles
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000231"},
            pack_overrides={"serial_number": "PK-C031"},
            snapshots=None,
        )
        west_vehicle_id = world["vehicle_id"]

        # Same model, same pack type, different region: eligible on every axis but one.
        east_vehicle = setup_vehicle(
            api,
            world["program_id"],
            vin="5YJ3E1EA7KF000232",
            region_code="US-EAST",
        )
        setup_installed_pack(api, east_vehicle["id"], serial_number="PK-C032")
        assert east_vehicle["region_code"] == "US-EAST"

        campaign_terms = {
            "target_defect": "THERMAL_MANAGEMENT",
            "software_version": "bms-4.3.0",
            "applies_to_pack_type": "ANY",
            "applies_to_model_code": "MX-90",
        }
        no_pilot = create_campaign(api, campaign_code="CMP-THM-11", **campaign_terms)
        with_pilot = create_campaign(
            api,
            campaign_code="CMP-THM-12",
            pilot_region_codes=["US-WEST"],
            **campaign_terms,
        )
        assert no_pilot["status"] == "DRAFT"
        assert no_pilot["release_scope"] is None
        assert no_pilot["pilot_region_codes"] == []

        validate_error(
            api.release_campaign(
                no_pilot["id"], release_payload("LIMITED"), world["admin_headers"]
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            expected_status=400,
        )

        # The refused release moved nothing at all.
        refused = read_campaign(api, no_pilot["id"])
        assert refused["status"] == "DRAFT"
        assert refused["release_scope"] is None
        assert refused["solicited_consent_count"] == 0
        assert refused["open_consent_count"] == 0
        assert refused["applied_count"] == 0
        _, no_pilot_meta = list_campaign_consents(api, no_pilot["id"])
        assert no_pilot_meta["total_count"] == 0

        released = validate_success(
            api.release_campaign(
                with_pilot["id"], release_payload("LIMITED"), world["admin_headers"]
            )
        )
        assert_remediation_campaign(released)
        assert released["status"] == "LIMITED_RELEASE"
        assert released["release_scope"] == "LIMITED"
        assert released["solicited_consent_count"] == 1
        assert released["open_consent_count"] == 1
        assert released["applied_count"] == 0

        rows, meta = list_campaign_consents(api, with_pilot["id"])
        assert meta["total_count"] == 1
        assert rows[0]["vehicle_id"] == west_vehicle_id
        assert_remediation_consent(rows[0])
        assert rows[0]["consent_status"] == "PENDING"
        assert [row["vehicle_id"] for row in rows] == [west_vehicle_id]
        assert east_vehicle["id"] not in [row["vehicle_id"] for row in rows]


class TestResubmitRequiresAnOpenInfoRequest:
    """Resubmit is legal from one state only, and its refusal costs nothing."""

    def test_a_premature_resubmit_neither_consumes_a_round_nor_repoints_the_claim(
        self, api
    ):
        """A SUBMITTED claim has no open request to answer.

        PRD 2.7: "Claim status `INFO_REQUESTED` for a resubmit —
        `ERR_INFO_REQUEST_NOT_OPEN`."

        PRD 3.4: "Opening an information request moves the claim from `SUBMITTED` to
        `INFO_REQUESTED`, optionally recording a `reason_note`, and increments
        `info_request_round` by one."

        PRD 3.4: "The technician answers by resubmitting, which returns the claim from
        `INFO_REQUESTED` to `SUBMITTED` and may carry a free-text `note` plus a
        replacement `assessment_id`. ... the claim is repointed at it and both
        `recommended_remedy` and `recommendation_basis` are recomputed from current
        pack, thermal and assessment state."

        Design: Corner/state_machines/resubmit_on_a_submitted_claim_returns_info_request_not_open
        """
        world = setup_submitted_claim_world(api)
        filed = world["claim"]
        assert filed["adjudication_status"] == "SUBMITTED"
        assert filed["info_request_round"] == 0
        assert filed["assessment_id"] == world["assessment_id"]

        validate_error(
            api.resubmit_claim(
                world["claim_id"],
                resubmit_payload(world["assessment_id"], note="premature resubmit"),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_INFO_REQUEST_NOT_OPEN.value,
            expected_status=409,
        )

        unchanged = read_claim(api, world["claim_id"], world["tech_headers"])
        assert unchanged["adjudication_status"] == "SUBMITTED"
        assert unchanged["info_request_round"] == 0
        assert unchanged["assessment_id"] == world["assessment_id"]
        # Two faulted modules against an allowance of MIN(3, 4) == 3 still recommend
        # the module remedy, so no recomputation was smuggled in by the refusal.
        assert unchanged["recommended_remedy"] == "MODULE_REPLACEMENT"
        assert unchanged["recommendation_basis"] == "MODULE_FAULT"


class TestApplyUpdateRequiresAGrant:
    """APPLIED is reachable from GRANTED alone, and the open set is not decremented."""

    def test_flashing_a_pending_consent_is_refused_and_no_counter_moves(self, api):
        """A solicitation is not a permission.

        PRD 3.8: "The consent's `consent_status` must be `GRANTED` — `PENDING`,
        `DECLINED`, `EXPIRED` and `APPLIED` all reject with
        `ERR_CONSENT_NOT_GRANTED`."

        PRD 3.8: "On success `consent_status` moves to `APPLIED`, `applied_at` is
        stamped with the current logical clock, and `applied_software_version`
        snapshots the campaign's `software_version` as it stands at that moment. The
        campaign's `applied_count` rises by one and its `open_consent_count` falls by
        one, and the campaign auto-closes if `open_consent_count` reaches zero."

        PRD 3.8: "`open_consent_count` is by definition the number of this campaign's
        consents in `PENDING` or `GRANTED`, and `applied_count` the number in
        `APPLIED`, while `solicited_consent_count` is a lifetime total that never
        falls."

        Design: Corner/state_machines/apply_update_on_a_pending_consent_returns_consent_not_granted
        """
        world = setup_released_campaign_world(
            api,
            "FIELD",
            campaign_overrides={"campaign_code": "CMP-CHG-51"},
            snapshots=None,
        )
        assert world["campaign"]["status"] == "FIELD_RELEASE"
        assert world["consent"]["consent_status"] == "PENDING"

        validate_error(
            api.apply_update(
                world["consent_id"],
                apply_update_payload(installer_note="flashing without a grant"),
                make_technician_headers(world["technician_id"]),
            ),
            ApiErrorId.ERR_CONSENT_NOT_GRANTED.value,
            expected_status=409,
        )

        consent = read_consent(api, world["consent_id"])
        assert consent["consent_status"] == "PENDING"
        assert consent["applied_at"] is None
        assert consent["applied_software_version"] is None
        assert consent["decision_at"] is None

        campaign = read_campaign(api, world["campaign_id"])
        assert campaign["status"] == "FIELD_RELEASE"
        assert campaign["applied_count"] == 0
        assert campaign["open_consent_count"] == 1
        assert campaign["solicited_consent_count"] == 1


class TestClosedClaimLockdown:
    """CLOSED fronts every claim-scoped action with one identifier."""

    def test_a_closed_denial_refuses_five_actions_the_same_way_and_a_dispute_differently(
        self, api
    ):
        """The lockdown outranks each action's own more specific state rule.

        PRD 2.7: "Terminal lockdown: no operation of any kind is accepted against a
        claim already `CLOSED` — `ERR_CLAIM_TERMINAL`. This guard fronts every
        claim-scoped operation: information request, resubmit, adjudicate, fulfil and
        close alike."

        PRD 3.5: "**Denying the claim** moves it from `SUBMITTED` to `DENIED` and
        requires an `override_justification` to be present, because a denial is by
        definition a departure from a remedy recommendation. It sets `denial_reason` to
        `ADJUDICATOR_DECISION` and zeroes the money: `remedy_cost_cents`,
        `owner_share_cents`, `oem_share_cents`, `admin_fee_cents` and `oem_total_cents`
        all read 0, `proration_factor` reads 0.0000, and the program's
        `accrued_liability_cents` is left entirely unchanged."

        PRD 3.6: "A claim may be closed only from `FULFILLED` or `DENIED`; anything
        else is refused with `ERR_CLAIM_NOT_CLOSABLE`."

        PRD 3.6: "closing a denial ends the dispute window, because the claim then
        leaves the disputable set and any later dispute filing is refused with
        `ERR_CLAIM_NOT_DISPUTABLE`."

        Design: Corner/state_machines/closed_claim_refuses_every_further_action
        """
        world = setup_submitted_claim_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000261"},
            pack_overrides={"serial_number": "PK-C061"},
        )
        adj_one = make_adjudicator_headers(ADJUDICATOR_1_ID)

        denied = validate_success(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload(
                    "DENIED",
                    override_justification="capacity within spec on re-review",
                ),
                adj_one,
            )
        )
        assert denied["adjudication_status"] == "DENIED"
        assert denied["denial_reason"] == "ADJUDICATOR_DECISION"
        assert denied["oem_total_cents"] == 0
        assert denied["proration_factor"] == pytest.approx(0.0000, abs=0.00005)
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 0

        closed = validate_success(
            api.close_claim(
                world["claim_id"], close_payload(closure_note="denial closed"), adj_one
            )
        )
        assert closed["adjudication_status"] == "CLOSED"

        terminal = ApiErrorId.ERR_CLAIM_TERMINAL.value

        # An information request would otherwise fail at ERR_CLAIM_NOT_ADJUDICABLE.
        validate_error(
            api.request_info(
                world["claim_id"], request_info_payload("after close"), adj_one
            ),
            terminal,
            expected_status=409,
        )
        # A resubmit would otherwise fail at ERR_INFO_REQUEST_NOT_OPEN.
        validate_error(
            api.resubmit_claim(
                world["claim_id"],
                resubmit_payload(world["assessment_id"], note="after close"),
                world["tech_headers"],
            ),
            terminal,
            expected_status=409,
        )
        # A second adjudication would otherwise fail at ERR_CLAIM_NOT_ADJUDICABLE.
        validate_error(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload(
                    "MODULE_REPLACEMENT", override_justification="reversal attempt"
                ),
                make_adjudicator_headers(ADJUDICATOR_2_ID),
            ),
            terminal,
            expected_status=409,
        )
        # A second close would otherwise fail at ERR_CLAIM_NOT_CLOSABLE.
        validate_error(
            api.close_claim(
                world["claim_id"], close_payload(closure_note="second close"), adj_one
            ),
            terminal,
            expected_status=409,
        )
        # A fulfilment would otherwise fail at ERR_CLAIM_NOT_FULFILLABLE.
        validate_error(
            api.fulfil_claim(
                world["claim_id"],
                fulfil_payload(world["technician_id"]),
                world["tech_headers"],
            ),
            terminal,
            expected_status=409,
        )

        # A dispute is not a claim-scoped POST, so it fails on the disputable set.
        validate_error(
            api.create_dispute(
                dispute_payload(
                    world["claim_id"],
                    closed["version"],
                    lab_name="Statewide Cell Lab",
                    owner_statement="capacity still low",
                ),
                world["owner_headers"],
            ),
            ApiErrorId.ERR_CLAIM_NOT_DISPUTABLE.value,
            expected_status=409,
        )

        final = read_claim(api, world["claim_id"], world["tech_headers"])
        assert final["adjudication_status"] == "CLOSED"
        assert final["info_request_round"] == 0
        assert final["oem_total_cents"] == 0
        assert final["denial_reason"] == "ADJUDICATOR_DECISION"
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 0


class TestRegulatoryFilingIsOnceOnly:
    """A replayed filing is refused and overwrites nothing on either center."""

    def test_a_second_filing_at_another_center_changes_neither_event_nor_center(self, api):
        """The first filing is authoritative; the second is a 409 and nothing else.

        PRD 3.7: "`notification_status` must be `PENDING`, or the filing is refused
        with `ERR_NOTIFICATION_ALREADY_FILED` — which is also what a second filing
        attempt receives."

        PRD 3.7: "The filing stamps `notification_filed_at` with the current logical
        clock and records `regulator_reference` and `reporting_service_center_id`. ...
        An on-time filing sets `notification_status` to `FILED` and has no compliance
        consequence whatsoever."

        PRD 3.7: "for `S3` it is `detected_at` plus seventy-two hours"

        PRD 3.7: "`event_status` reads `COMPLETE` when `containment_status` is
        `CONTAINMENT_CLOSED` *and* `notification_status` is `NOT_REQUIRED`, `FILED` or
        `LATE_FILED`, and `OPEN` in every other case."

        Design: Corner/state_machines/second_regulatory_notification_returns_notification_already_filed
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000271"},
            pack_overrides={"serial_number": "PK-C071"},
            snapshots=None,
        )
        second_center = setup_center(api, name="East HV Center", region_code="US-EAST")

        event = report_thermal_event(
            api,
            world,
            severity="S3",
            detected_at="2026-07-31T00:00:00Z",
            affected_module_positions=[9],
        )
        assert event["notification_status"] == "PENDING"
        assert_same_instant(
            event["notification_deadline_at"],
            "2026-08-03T00:00:00Z",
            "notification_deadline_at",
        )

        filed = validate_success(
            api.file_regulatory_notification(
                world["event_id"],
                regulatory_notification_payload(
                    world["center_id"], regulator_reference="REG-2026-0001"
                ),
                world["liaison_headers"],
            )
        )
        assert filed["notification_status"] == "FILED"
        assert_same_instant(
            filed["notification_filed_at"],
            "2026-08-01T00:00:00Z",
            "notification_filed_at",
        )
        assert_same_instant(
            filed["notification_deadline_at"],
            "2026-08-03T00:00:00Z",
            "notification_deadline_at",
        )
        assert filed["regulator_reference"] == "REG-2026-0001"
        assert filed["reporting_service_center_id"] == world["center_id"]

        validate_error(
            api.file_regulatory_notification(
                world["event_id"],
                regulatory_notification_payload(
                    second_center["id"], regulator_reference="REG-2026-0002"
                ),
                world["liaison_headers"],
            ),
            ApiErrorId.ERR_NOTIFICATION_ALREADY_FILED.value,
            expected_status=409,
        )

        replayed = read_event(api, world["event_id"])
        assert replayed["notification_status"] == "FILED"
        assert replayed["regulator_reference"] == "REG-2026-0001"
        assert replayed["reporting_service_center_id"] == world["center_id"]
        assert_same_instant(
            replayed["notification_filed_at"],
            "2026-08-01T00:00:00Z",
            "notification_filed_at",
        )
        # Settling the regulatory dimension alone does not complete the event.
        assert replayed["containment_status"] == "DETECTED"
        assert replayed["event_status"] == "OPEN"
        assert_event_status_join(replayed)

        # An on-time filing damages nobody, and the named-then-refused center least of all.
        for center_id in (world["center_id"], second_center["id"]):
            center = read_center(api, center_id)
            assert center["late_notification_count"] == 0
            assert center["compliance_score"] == 100


class TestAssessmentSupersession:
    """One create fires three consequences, and all three are observable."""

    def test_a_second_diagnostic_supersedes_the_first_bumps_the_vehicle_and_blocks_its_claim(
        self, api
    ):
        """The superseded diagnostic can no longer back a claim.

        PRD 3.3: "Finally, writing an assessment closes the book on the vehicle's
        earlier ones: every prior assessment on the same `vehicle_id` has `superseded`
        set to true, and a superseded assessment can no longer back a claim. The
        vehicle's `version` increments by one as part of the same operation, which is
        precisely why the next writer's `expected_vehicle_version` must be refreshed."

        PRD 3.4: "an assessment whose `superseded` flag is true is refused with
        `ERR_ASSESSMENT_SUPERSEDED`"

        PRD 3.3: "For `TELEMATICS_FLEET`, the denominator `nominal_basis_kwh` is the
        pack's full beginning-of-life `nominal_capacity_kwh`; faulted modules are *not*
        excluded from it."

        Design: Corner/state_machines/new_assessment_supersedes_the_prior_one_and_bumps_vehicle_version
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000281"},
            pack_overrides={"serial_number": "PK-C081"},
        )
        version_before = read_vehicle_version(
            api, world["vehicle_id"], world["technician_id"]
        )

        first = add_assessment(api, world, module_fault_positions=[3, 7])
        assert_soh_assessment(first)
        assert first["superseded"] is False
        assert first["diagnostic_validity"] == "VALID"
        assert first["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert first["coverage_position"] == "IN_COVERAGE"
        assert first["qualifies_for_claim"] is True

        version_after = read_vehicle_version(
            api, world["vehicle_id"], world["technician_id"]
        )
        assert version_after == version_before + 1

        # Positions 3 and 7 are already FAULTED, and the fleet denominator is the full
        # 80.000 either way, so the second reading lands on the same retention figure.
        second = add_assessment(api, world)
        assert_soh_assessment(second)
        assert second["superseded"] is False
        assert second["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert second["id"] != first["id"]

        superseded = read_assessment(api, first["id"], world["tech_headers"])
        assert superseded["superseded"] is True

        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    first["id"],
                    world["technician_id"],
                ),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_ASSESSMENT_SUPERSEDED.value,
            expected_status=409,
        )
        _, claim_meta = list_claims(api, vehicle_id=world["vehicle_id"])
        assert claim_meta["total_count"] == 0
