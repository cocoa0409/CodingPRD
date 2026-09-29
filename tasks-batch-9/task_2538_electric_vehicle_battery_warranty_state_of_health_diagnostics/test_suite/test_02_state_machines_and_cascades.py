"""Non-linear lifecycles and the cascades that fan out from a single write.

The claim information-request cycle returns to a state it has already occupied
with different data behind it; a thermal event runs two lifecycles at once that
touch at exactly one point; and an S4 report or an owner's refusal reaches four
entities deep in one operation.
"""

import pytest

from test_helpers import (
    assert_same_instant,
    ApiErrorId,
    add_assessment,
    add_claim,
    adjudicate,
    advance_containment,
    assert_denied_claim_zeroed,
    assert_event_status_join,
    assert_module_statuses,
    assert_settlement_waterfall,
    assert_thermal_event,
    decide_consent,
    file_notification,
    list_modules,
    read_campaign,
    read_center,
    read_claim,
    read_consent,
    read_event,
    read_pack,
    read_program,
    read_vehicle,
    report_thermal_event,
    request_info_payload,
    resubmit_payload,
    setup_base_world,
    setup_released_campaign_world,
    setup_submitted_claim_world,
    validate_error,
    validate_success,
)


class TestInfoRequestCycle:
    """SUBMITTED is re-entered with a different recommendation behind it."""

    def test_resubmitting_a_new_assessment_recomputes_the_remedy_recommendation(self, api):
        """One faulted module recommends a module swap; five recommend a pack.

        PRD 3.4: "the claim is repointed at it and both `recommended_remedy` and
        `recommendation_basis` are recomputed from current pack, thermal and
        assessment state, with `coverage_position` re-read from the possibly-new
        assessment."

        Design: Difficulty/non_linear_state_machine/claim_info_request_cycle_returns_to_submitted_with_changed_recommendation
        """
        world = setup_submitted_claim_world(
            api,
            module_fault_positions=(3,),
            program_overrides={"info_request_limit": 2},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assert world["claim"]["recommended_remedy"] == "MODULE_REPLACEMENT"
        assert world["claim"]["recommendation_basis"] == "MODULE_FAULT"

        opened = validate_success(
            api.request_info(
                world["claim_id"],
                request_info_payload("please widen the module survey"),
                world["adjudicator_headers"],
            )
        )
        assert opened["adjudication_status"] == "INFO_REQUESTED"
        assert opened["info_request_round"] == 1

        second = add_assessment(api, world, module_fault_positions=[1, 2, 3, 4, 5])
        assert second["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert second["superseded"] is False

        resubmitted = validate_success(
            api.resubmit_claim(
                world["claim_id"],
                resubmit_payload(second["id"], note="five modules faulted"),
                world["tech_headers"],
            )
        )
        assert resubmitted["adjudication_status"] == "SUBMITTED"
        assert resubmitted["assessment_id"] == second["id"]
        assert resubmitted["recommended_remedy"] == "PACK_REPLACEMENT"
        assert resubmitted["recommendation_basis"] == "MODULE_ALLOWANCE"

        # The return to SUBMITTED does not reset the counter.
        assert resubmitted["info_request_round"] == 1

    def test_supersession_and_the_information_request_ceiling_hold_together(self, api):
        """The third request is refused and leaves the claim SUBMITTED at round two.

        PRD 3.4: "Crucially, the return to `SUBMITTED` does *not* reset
        `info_request_round`, so with the default limit of two the adjudicator's
        third information request on the same claim is refused."

        Design: Difficulty/non_linear_state_machine/claim_info_request_cycle_returns_to_submitted_with_changed_recommendation
        """
        world = setup_submitted_claim_world(
            api,
            module_fault_positions=(3,),
            program_overrides={"info_request_limit": 2},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        first_assessment_id = world["assessment_id"]

        validate_success(
            api.request_info(
                world["claim_id"], request_info_payload(), world["adjudicator_headers"]
            )
        )
        second = add_assessment(api, world, module_fault_positions=[1, 2, 3, 4, 5])

        # Writing the replacement diagnostic closed the book on the first one.
        superseded = validate_success(
            api.get_assessment(first_assessment_id, world["tech_headers"])
        )
        assert superseded["superseded"] is True
        assert second["superseded"] is False

        validate_success(
            api.resubmit_claim(
                world["claim_id"], resubmit_payload(second["id"]), world["tech_headers"]
            )
        )
        second_round = validate_success(
            api.request_info(
                world["claim_id"], request_info_payload(), world["adjudicator_headers"]
            )
        )
        assert second_round["info_request_round"] == 2

        validate_success(
            api.resubmit_claim(
                world["claim_id"], resubmit_payload(second["id"]), world["tech_headers"]
            )
        )

        validate_error(
            api.request_info(
                world["claim_id"], request_info_payload(), world["adjudicator_headers"]
            ),
            ApiErrorId.ERR_INFO_REQUEST_LIMIT_EXCEEDED.value,
            expected_status=409,
        )

        after = read_claim(api, world["claim_id"], world["tech_headers"])
        assert after["adjudication_status"] == "SUBMITTED"
        assert after["info_request_round"] == 2


class TestThermalEventTwoDimensions:
    """Containment and notification advance independently and touch once."""

    def test_containment_ordering_and_the_single_notification_interlock(self, api):
        """Step three is refused twice — once out of order, once for the filing.

        PRD 3.7: "Step 3 closes containment and moves `containment_status` from
        `PACK_QUARANTINED` to `CONTAINMENT_CLOSED`. Beyond the ordering requirement
        it demands that the regulatory dimension already be settled:
        `notification_status` must be `NOT_REQUIRED`, `FILED` or `LATE_FILED`."

        Design: Difficulty/non_linear_state_machine/thermal_event_parallel_containment_and_notification_dimensions
        """
        world = setup_base_world(api, snapshot_overrides={"coolant_temp_c": 20.0})
        event = report_thermal_event(
            api,
            world,
            severity="S3",
            detected_at="2026-07-30T00:00:00Z",
            affected_module_positions=[4],
            source="TELEMATICS",
        )
        assert_thermal_event(event)
        assert event["containment_status"] == "DETECTED"
        assert event["containment_steps_completed"] == 0
        assert event["notification_status"] == "PENDING"
        assert_same_instant(event["notification_deadline_at"], "2026-08-02T00:00:00Z", "notification_deadline_at")
        assert event["event_status"] == "OPEN"

        isolated = advance_containment(api, world, 1)
        assert isolated["containment_status"] == "ISOLATED"
        assert isolated["containment_steps_completed"] == 1

        # Skipping step two is refused and consumes nothing.
        validate_error(
            api.containment_step(
                world["event_id"],
                {"step_index": 3, "step_note": "premature close"},
                world["tech_headers"],
            ),
            ApiErrorId.ERR_CONTAINMENT_STEP_OUT_OF_ORDER.value,
            expected_status=409,
        )
        assert read_event(api, world["event_id"])["containment_steps_completed"] == 1

        quarantined = advance_containment(api, world, 2)
        assert quarantined["containment_status"] == "PACK_QUARANTINED"
        assert quarantined["containment_steps_completed"] == 2
        assert quarantined["event_status"] == "OPEN"

        # In order this time, but the regulatory dimension is still unsettled.
        validate_error(
            api.containment_step(
                world["event_id"],
                {"step_index": 3, "step_note": "close attempt"},
                world["tech_headers"],
            ),
            ApiErrorId.ERR_NOTIFICATION_STILL_PENDING.value,
            expected_status=409,
        )
        held = read_event(api, world["event_id"])
        assert held["containment_steps_completed"] == 2
        assert held["containment_status"] == "PACK_QUARANTINED"

        filed = file_notification(api, world, regulator_reference="NHTSA-2026-0091")
        assert filed["notification_status"] == "FILED"
        assert_same_instant(filed["notification_filed_at"], "2026-08-01T00:00:00Z", "notification_filed_at")
        assert filed["regulator_reference"] == "NHTSA-2026-0091"
        assert filed["reporting_service_center_id"] == world["center_id"]
        assert filed["containment_status"] == "PACK_QUARANTINED"
        assert filed["event_status"] == "OPEN"

        center = read_center(api, world["center_id"])
        assert center["late_notification_count"] == 0
        assert center["compliance_score"] == 100

        closed = advance_containment(api, world, 3)
        assert closed["containment_status"] == "CONTAINMENT_CLOSED"
        assert closed["containment_steps_completed"] == 3
        assert closed["event_status"] == "COMPLETE"
        assert_event_status_join(closed)

    def test_s3_report_quarantines_the_pack_and_immobilizes_the_vehicle(self, api):
        """The safety cascade lands before any containment step is recorded.

        PRD 3.7: "An `S3` or `S4` report also fires the safety cascade described in
        section 2.8: the pack's `damaged_defective` becomes true, its
        `hazmat_classification` becomes `UN3536`, and its `status` moves from
        `IN_SERVICE` to `QUARANTINED`."

        Design: Difficulty/non_linear_state_machine/thermal_event_parallel_containment_and_notification_dimensions
        """
        world = setup_base_world(api, snapshot_overrides={"coolant_temp_c": 20.0})
        report_thermal_event(
            api,
            world,
            severity="S3",
            detected_at="2026-07-30T00:00:00Z",
            affected_module_positions=[4],
            source="TELEMATICS",
        )

        pack = read_pack(api, world["pack_id"])
        assert pack["status"] == "QUARANTINED"
        assert pack["damaged_defective"] is True
        assert pack["hazmat_classification"] == "UN3536"

        vehicle = read_vehicle(api, world["vehicle_id"])
        assert vehicle["status"] == "IMMOBILIZED"
        assert vehicle["warranty_hold"] is True

        modules, _ = list_modules(api, world["pack_id"], limit=100)
        assert_module_statuses(modules, {4: "FAULTED"})
        by_position = {row["position_index"]: row for row in modules}
        assert by_position[4]["thermal_runaway_flag"] is True
        assert by_position[5]["thermal_runaway_flag"] is False
        assert by_position[5]["status"] == "HEALTHY"


class TestS4CascadeToCampaignClosure:
    """One S4 report reaches pack, module, vehicle, consent and campaign."""

    def test_s4_report_expires_the_consent_and_auto_closes_the_campaign(self, api):
        """Four links in one write, and a charging campaign is closed not suspended.

        PRD 3.7: "every remediation consent on that vehicle in `PENDING` or
        `GRANTED` moves to `EXPIRED`; and each affected campaign recomputes
        `open_consent_count` and auto-closes if that reaches zero while it is in
        `LIMITED_RELEASE` or `FIELD_RELEASE`."

        Design: Difficulty/transitive_cascade/s4_thermal_event_cascades_pack_to_vehicle_to_consents_to_campaign_closure
        """
        world = setup_released_campaign_world(
            api,
            release_scope="LIMITED",
            campaign_overrides={
                "campaign_code": "CMP-CHG-01",
                "target_defect": "CHARGING",
                "software_version": "2026.28.1",
                "applies_to_pack_type": "ANY",
                "pilot_region_codes": ["US-WEST"],
            },
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assert world["campaign"]["status"] == "LIMITED_RELEASE"
        assert world["campaign"]["solicited_consent_count"] == 1
        assert world["campaign"]["open_consent_count"] == 1
        assert world["consent"]["consent_status"] == "PENDING"

        event = report_thermal_event(
            api,
            world,
            severity="S4",
            detected_at="2026-07-31T12:00:00Z",
            affected_module_positions=[6, 7],
        )
        assert_same_instant(event["notification_deadline_at"], "2026-08-01T12:00:00Z", "notification_deadline_at")
        assert event["notification_status"] == "PENDING"
        assert event["event_status"] == "OPEN"

        # Link one: the pack.
        pack = read_pack(api, world["pack_id"])
        assert pack["status"] == "QUARANTINED"
        assert pack["damaged_defective"] is True
        assert pack["hazmat_classification"] == "UN3536"

        # Link two: the named modules.
        modules, _ = list_modules(api, world["pack_id"], limit=100)
        assert_module_statuses(modules, {6: "FAULTED", 7: "FAULTED"})
        by_position = {row["position_index"]: row for row in modules}
        assert by_position[6]["thermal_runaway_flag"] is True
        assert by_position[7]["thermal_runaway_flag"] is True

        # Link three: the vehicle.
        vehicle = read_vehicle(api, world["vehicle_id"])
        assert vehicle["status"] == "IMMOBILIZED"
        assert vehicle["warranty_hold"] is True

        # Link four: the consent, and through it the campaign.
        consent = read_consent(api, world["consent_id"])
        assert consent["consent_status"] == "EXPIRED"

        campaign = read_campaign(api, world["campaign_id"])
        assert campaign["open_consent_count"] == 0
        assert campaign["solicited_consent_count"] == 1
        assert campaign["applied_count"] == 0
        assert campaign["status"] == "CLOSED"

        # A CHARGING campaign is outside the S4 suspension filter entirely.
        assert campaign["status"] != "SUSPENDED"

    def test_a_thermal_management_campaign_is_suspended_instead_of_closed(self, api):
        """Suspension is evaluated before consent expiry, so the campaign survives closure.

        PRD 3.7: "For `S4` only, and evaluated *before* the consent-expiry step,
        every campaign whose `target_defect` is `THERMAL_MANAGEMENT`, whose
        `applies_to_model_code` equals the vehicle's `model_code` and whose
        `status` is `LIMITED_RELEASE` or `FIELD_RELEASE` moves to `SUSPENDED` — and
        because a suspended campaign never auto-closes, that ordering is what keeps
        a thermally suspect campaign from being silently retired."

        Design: Difficulty/transitive_cascade/s4_thermal_event_cascades_pack_to_vehicle_to_consents_to_campaign_closure
        """
        world = setup_released_campaign_world(
            api,
            release_scope="LIMITED",
            campaign_overrides={
                "campaign_code": "CMP-THM-01",
                "target_defect": "THERMAL_MANAGEMENT",
                "software_version": "2026.28.1",
                "applies_to_pack_type": "ANY",
                "pilot_region_codes": ["US-WEST"],
            },
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assert world["campaign"]["status"] == "LIMITED_RELEASE"

        report_thermal_event(
            api,
            world,
            severity="S4",
            detected_at="2026-07-31T12:00:00Z",
            affected_module_positions=[6, 7],
        )

        consent = read_consent(api, world["consent_id"])
        assert consent["consent_status"] == "EXPIRED"

        campaign = read_campaign(api, world["campaign_id"])
        assert campaign["open_consent_count"] == 0
        assert campaign["status"] == "SUSPENDED"
        assert campaign["status"] != "CLOSED"


class TestConsentDeclineCascade:
    """A refusal closes the campaign and unwinds the accrual exactly."""

    def test_decline_denies_the_software_claim_and_reverses_the_ledger(self, api):
        """21,167 cents booked at adjudication is removed to the cent on refusal.

        PRD 3.8: "that claim collapses to `DENIED` with `denial_reason` set to
        `CONSENT_DECLINED`, its `remedy_cost_cents`, `owner_share_cents`,
        `oem_share_cents`, `admin_fee_cents` and `oem_total_cents` are reset to
        zero, and the program's `accrued_liability_cents` is reduced by the
        `oem_total_cents` that adjudication had booked."

        Design: Difficulty/transitive_cascade/consent_decline_cascades_campaign_closure_and_liability_reversal
        """
        world = setup_released_campaign_world(
            api,
            release_scope="FIELD",
            campaign_overrides={
                "campaign_code": "CMP-CHG-02",
                "target_defect": "CHARGING",
                "software_version": "2026.28.1",
                "applies_to_pack_type": "ANY",
            },
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assert world["campaign"]["status"] == "FIELD_RELEASE"

        # No faulted module at all, so the ladder falls through to software.
        add_assessment(api, world)
        claim = add_claim(api, world)
        assert claim["recommended_remedy"] == "SOFTWARE_REMEDIATION"
        assert claim["recommendation_basis"] == "NO_MODULE_FAULT"

        approved = adjudicate(
            api,
            world,
            "SOFTWARE_REMEDIATION",
            linked_campaign_id=world["campaign_id"],
        )
        assert_settlement_waterfall(approved)
        assert approved["adjudication_status"] == "APPROVED_SOFTWARE"
        assert approved["linked_campaign_id"] == world["campaign_id"]

        # Zero parts, half an hour of labour at 18,333 (9,166.5 -> 9,167) and the
        # diagnostic fee, with no freight at all.
        assert approved["remedy_cost_cents"] == 21167
        assert approved["owner_share_cents"] == 0
        assert approved["oem_share_cents"] == 21167
        assert approved["admin_fee_cents"] == 0
        assert approved["oem_total_cents"] == 21167
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 21167

        declined = decide_consent(
            api, world["consent_id"], world["vehicle_id"], "DECLINE"
        )
        assert declined["consent_status"] == "DECLINED"
        assert_same_instant(declined["decision_at"], "2026-08-01T00:00:00Z", "decision_at")

        campaign = read_campaign(api, world["campaign_id"])
        assert campaign["open_consent_count"] == 0
        assert campaign["solicited_consent_count"] == 1
        assert campaign["applied_count"] == 0
        assert campaign["status"] == "CLOSED"

        denied = read_claim(api, world["claim_id"])
        assert_denied_claim_zeroed(denied)
        assert denied["denial_reason"] == "CONSENT_DECLINED"
        assert denied["oem_total_cents"] == 0

        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 0

    def test_a_grant_moves_no_counter_and_leaves_the_campaign_open(self, api):
        """GRANTED stays inside the open set, so nothing auto-closes.

        PRD 3.8: "A `GRANT` moves `consent_status` to `GRANTED` and changes no
        counter at all, because `GRANTED` remains inside the open set alongside
        `PENDING`; the campaign's `open_consent_count` is therefore unchanged and no
        auto-close can be triggered by a grant."

        Design: Difficulty/transitive_cascade/consent_decline_cascades_campaign_closure_and_liability_reversal
        """
        world = setup_released_campaign_world(
            api,
            release_scope="FIELD",
            campaign_overrides={
                "campaign_code": "CMP-CHG-02",
                "target_defect": "CHARGING",
                "software_version": "2026.28.1",
                "applies_to_pack_type": "ANY",
            },
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        add_assessment(api, world)
        add_claim(api, world)
        approved = adjudicate(
            api,
            world,
            "SOFTWARE_REMEDIATION",
            linked_campaign_id=world["campaign_id"],
        )
        assert approved["oem_total_cents"] == 21167

        granted = decide_consent(api, world["consent_id"], world["vehicle_id"], "GRANT")
        assert granted["consent_status"] == "GRANTED"
        assert_same_instant(granted["decision_at"], "2026-08-01T00:00:00Z", "decision_at")

        campaign = read_campaign(api, world["campaign_id"])
        assert campaign["open_consent_count"] == 1
        assert campaign["status"] == "FIELD_RELEASE"

        # The claim and the ledger are untouched by a grant.
        still_approved = read_claim(api, world["claim_id"])
        assert still_approved["adjudication_status"] == "APPROVED_SOFTWARE"
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 21167
