"""Refusals proved by their neighbours: each guard is shown to bite on the
forbidden call while the adjacent, legitimate call in the same state goes
through untouched."""

from test_helpers import (
    ADMIN,
    ILLNESS_S1_COMPLAINT,
    ApiErrorId,
    add_complaint,
    add_contact,
    add_kit,
    add_lot,
    add_plant,
    add_remedy,
    add_template,
    assert_severity,
    assert_two_decimal_value,
    complaint_payload,
    consumer_payload,
    current_complaint_version,
    determine_report,
    escalate_to_recall_evaluation,
    find_report,
    open_investigation,
    plant_payload,
    product_payload,
    production_line_payload,
    remedy_payload,
    response_template_payload,
    sample_kit_payload,
    seed_base_world,
    seed_triaged_complaint,
    staff_user_payload,
    submit_report,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

SOFT_FOREIGN_MATTER = dict(complaint_type="FOREIGN_MATERIAL", foreign_object_class="SOFT")
SHARP_PACKAGING = dict(
    complaint_type="PACKAGING",
    foreign_object_class="HARD_SHARP",
    medical_attention_sought=True,
    symptom_codes=["CUT", "PAIN", "SWELLING", "BLEEDING"],
)
LOT_WINDOW = dict(window_start="2026-07-20T00:00:00Z", window_end="2026-08-02T00:00:00Z")


# ---------------------------------------------------------------------------
# Intake guards
# ---------------------------------------------------------------------------
class TestContactClosure:
    def test_a_closed_touch_is_sealed_while_a_logged_one_keeps_working(self, api):
        """CLOSED_NO_COMPLAINT refuses a complaint; LOGGED happily takes a second.

        PRD: "On `POST /complaints`, the source contact is `OPEN` or `LOGGED` —
        otherwise `ERR_CONTACT_CLOSED` (409)."

        Design: Corner/errors/corner_closed_contact_cannot_spawn_a_complaint
        """
        world = seed_base_world(api, actor_keys=("ag1",))
        add_contact(
            api, world, "cta", channel="SOCIAL", raw_message="Where can I buy this?"
        )
        add_contact(api, world, "ctb", channel="PHONE", raw_message="Stale pack.")
        add_complaint(api, world, "p1", contact_key="ctb", complaint_type="QUALITY")
        agent = world.headers("ag1")
        enquiry_id = world["contacts"]["cta"]["id"]
        productive_id = world["contacts"]["ctb"]["id"]

        closed = validate_success(
            api.close_contact_no_complaint(
                enquiry_id, {"reason": "Enquiry only."}, agent
            )
        )
        assert closed["status"] == "CLOSED_NO_COMPLAINT"

        sealed = api.create_complaint(
            complaint_payload(enquiry_id, complaint_type="QUALITY"), agent
        )
        validate_error(sealed, ApiErrorId.CONTACT_CLOSED, 409)

        logged = validate_success(api.get_contact(productive_id, agent))
        assert logged["status"] == "LOGGED"
        assert logged["complaint_count"] == 1

        second = validate_success(
            api.create_complaint(
                complaint_payload(productive_id, complaint_type="PACKAGING"), agent
            ),
            201,
        )
        assert second["contact_id"] == productive_id

        reread = validate_success(api.get_contact(productive_id, agent))
        assert reread["status"] == "LOGGED"
        assert reread["complaint_count"] == 2


class TestUniqueCodes:
    def test_every_unique_code_clashes_except_a_line_code_under_another_plant(
        self, api
    ):
        """Seven codes collide; the eighth is scoped to its plant and is free again.

        PRD: "Unique codes are unique: `staff_code`, `external_ref`,
        `plant_code`, `sku`, `kit_code`, `template_code`, and `line_code` within
        its plant — otherwise `ERR_DUPLICATE_CODE` (409)."

        Design: Corner/errors/corner_every_unique_field_rejects_a_duplicate
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_plant(
            api, world, "p2", plant_code="P-ATL", name="Atlanta Bakery", region="SE"
        )
        add_template(
            api, world, "t1", template_code="T-ANY", title="General", body="Thanks.",
            activate=False,
        )
        seed_triaged_complaint(
            api, world, contact_overrides={"raw_message": "Soft matter."},
            **SOFT_FOREIGN_MATTER,
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        add_kit(api, world, complaint_id, "k1", kit_code="K-B01", seal_id_issued="SEAL-B01")
        agent = world.headers("ag1")
        supervisor = world.headers("sup1")
        first_plant_id = world["plant"]["id"]

        clashes = (
            api.create_staff_user(
                staff_user_payload("AG1", "Impostor", "CARE_AGENT"), ADMIN
            ),
            api.create_consumer(consumer_payload("C-1", "Other Person"), agent),
            api.create_plant(plant_payload("P-CHI", "Second Chicago", "MW"), ADMIN),
            api.create_production_line(
                production_line_payload(first_plant_id, "L-01", 8000), ADMIN
            ),
            api.create_product(
                product_payload("SKU-CRACKER", "Other Crackers"), ADMIN
            ),
            api.create_sample_kit(
                sample_kit_payload(complaint_id, "K-B01", "SEAL-B02"), agent
            ),
            api.create_response_template(
                response_template_payload("T-ANY", "Clash", "Clash."), supervisor
            ),
        )
        for response in clashes:
            validate_error(response, ApiErrorId.DUPLICATE_CODE, 409)

        elsewhere = validate_success(
            api.create_production_line(
                production_line_payload(world["plants"]["p2"]["id"], "L-01", 8000),
                ADMIN,
            ),
            201,
        )
        assert elsewhere["line_code"] == "L-01"
        assert elsewhere["plant_id"] == world["plants"]["p2"]["id"]


# ---------------------------------------------------------------------------
# Fiscal ceiling
# ---------------------------------------------------------------------------
class TestGoodwillCeiling:
    def test_one_cent_of_request_rounds_the_payout_past_the_ceiling(self, api):
        """23,809 cents lands on 24,999; 23,810 rounds up to 25,001 and is refused.

        PRD: "A `payout_cents` exceeding 25,000 is rejected outright with
        `ERR_GOODWILL_ABOVE_MAX`, and that ceiling is re-checked at authoring, at
        submission, and at decision time."

        Design: Corner/errors/corner_goodwill_above_max_payout_is_refused_at_the_cent
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        seed_triaged_complaint(
            api, world, complaint_type="QUALITY",
            contact_overrides={"channel": "EMAIL", "raw_message": "Very unhappy."},
        )
        complaint_id = world["complaints"]["cp1"]["id"]

        accepted = add_remedy(
            api, world, complaint_id, "rm1", remedy_type="COUPON",
            requested_value_cents=23809,
        )
        assert accepted["base_value_cents"] == 23809
        assert accepted["uplift_cents"] == 1190
        assert accepted["payout_cents"] == 24999
        assert accepted["authority_tier_required"] == "TIER_3"
        assert_two_decimal_value(accepted["uplift_pct"], 0.05)

        over_the_edge = api.create_remedy(
            remedy_payload(
                complaint_id,
                current_complaint_version(api, world, complaint_id),
                remedy_type="COUPON",
                requested_value_cents=23810,
            ),
            world.headers("ag1"),
        )
        validate_error(over_the_edge, ApiErrorId.GOODWILL_ABOVE_MAX, 422)

        _rows, meta = validate_paginated(api.list_remedies(world.headers("ag1")))
        assert meta["total_count"] == 1
        survivor = validate_success(
            api.get_remedy(accepted["id"], world.headers("ag1"))
        )
        assert survivor["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Regulatory report guards
# ---------------------------------------------------------------------------
class TestReportLifecycleGuards:
    def test_a_second_report_and_an_early_filing_are_both_refused(self, api):
        """One live report per complaint, and filing only from a reportable verdict.

        PRD: "The report is `OPEN` when a determination is recorded and
        `DETERMINED_REPORTABLE` when it is submitted, and is not already terminal
        when it is withdrawn — otherwise `ERR_REPORT_STATE_INVALID` (409)."

        Design: Corner/errors/corner_report_lifecycle_guards_reject_second_open_and_early_submit
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ro1", "ro2"))
        seed_triaged_complaint(
            api, world,
            contact_overrides={
                "channel": "EMAIL",
                "raw_message": "Soft matter, no injury.",
            },
            **SOFT_FOREIGN_MATTER,
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        officer = world.headers("ro1")
        first = validate_success(
            api.create_regulatory_report(
                {"complaint_id": complaint_id, "report_kind": "FOREIGN_MATERIAL_INJURY"},
                officer,
            ),
            201,
        )
        assert first["status"] == "OPEN"

        second = api.create_regulatory_report(
            {"complaint_id": complaint_id, "report_kind": "ADVERSE_EVENT"}, officer
        )
        validate_error(second, ApiErrorId.REPORT_ALREADY_OPEN, 409)

        early = api.submit_regulatory_report(
            first["id"], {"agency_reference": "AG-00001"}, officer
        )
        # PRD 2.9: step 17 (regulatory dimension) is ranked above step 23 (report
        # state), so filing while the complaint is still ESCALATED reports the
        # regulatory-dimension failure.
        validate_error(early, ApiErrorId.REGULATORY_STATE_INVALID, 409)

        determined = determine_report(
            api, world, first["id"], "NOT_REPORTABLE",
            determination_note="Below the threshold.",
        )
        assert determined["status"] == "DETERMINED_NOT_REPORTABLE"

        wrong_verdict_to_file = api.submit_regulatory_report(
            first["id"], {"agency_reference": "AG-00002"}, world.headers("ro2")
        )
        validate_error(wrong_verdict_to_file, ApiErrorId.REGULATORY_STATE_INVALID, 409)

        second_verdict = api.determine_regulatory_report(
            first["id"],
            {"determination": "REPORTABLE", "determination_note": "Changed my mind."},
            officer,
        )
        validate_error(second_verdict, ApiErrorId.REGULATORY_STATE_INVALID, 409)


class TestS1IsAlwaysReportable:
    def test_the_most_severe_band_cannot_be_determined_non_reportable(self, api):
        """NOT_REPORTABLE is refused and stamps nothing; REPORTABLE then succeeds.

        PRD: "The most severe band can never be determined non-reportable, and
        the attempt is refused with `ERR_S1_MUST_BE_REPORTABLE`."

        Design: Corner/errors/corner_s1_complaint_cannot_be_determined_not_reportable
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ro1"))
        seed_triaged_complaint(
            api, world,
            contact_overrides={"raw_message": "Ill after eating, saw a doctor."},
            **ILLNESS_S1_COMPLAINT,
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        assert_severity(
            world["complaints"]["cp1"], adjudicated_score=93.53, effective_band="S1"
        )
        report = find_report(api, world, complaint_id)
        assert report["status"] == "OPEN"
        officer = world.headers("ro1")

        refused = api.determine_regulatory_report(
            report["id"],
            {
                "determination": "NOT_REPORTABLE",
                "determination_note": "Attempting to close it out.",
            },
            officer,
        )
        validate_error(refused, ApiErrorId.S1_MUST_BE_REPORTABLE, 422)

        untouched = validate_success(api.get_regulatory_report(report["id"], officer))
        assert untouched["status"] == "OPEN"
        assert untouched["determined_by_ref"] is None

        determined = determine_report(
            api, world, report["id"], "REPORTABLE", determination_note="Reportable."
        )
        assert determined["status"] == "DETERMINED_REPORTABLE"
        complaint = validate_success(
            api.get_complaint(complaint_id, world.headers("ag1"))
        )
        assert complaint["regulatory_status"] == "REPORTABLE"


# ---------------------------------------------------------------------------
# Trend-signal escalation guards
# ---------------------------------------------------------------------------
def _seed_three_mug_complaints(api, *, batch_code, reported_code, descriptors):
    """Three complaints of one shape on an unregulated hundred-thousand-unit lot."""
    world = seed_base_world(
        api,
        actor_keys=("ag1", "sup1", "ql1"),
        product="mug",
        lot={"batch_code": batch_code, "units_produced": 100000},
    )
    add_contact(api, world, "ct1", channel="WEB", raw_message="Three of them spoiled.")
    for key in ("m1", "m2", "m3"):
        complaint = validate_success(
            api.create_complaint(
                complaint_payload(
                    world["contacts"]["ct1"]["id"],
                    reported_batch_code=reported_code,
                    **descriptors,
                ),
                world.headers("ag1"),
            ),
            201,
        )
        world["complaints"][key] = triage(api, world, complaint["id"])
    return world


class TestRecallSeverityGate:
    def test_a_signal_of_mild_members_clears_the_rate_gate_but_not_the_severity_gate(
        self, api
    ):
        """Three S3 members are enough to detect a trend and not enough to recall it.

        PRD: "Escalating an open investigation to recall evaluation, optionally
        with an `escalation_note`, moves the signal `INVESTIGATION_OPEN →
        RECALL_EVALUATION` and requires that at least one member complaint has an
        `effective_severity_band` of `S1` or `S2`; low-severity trends are
        investigated but never escalated, and the attempt otherwise fails with
        `ERR_SEVERITY_TOO_LOW_FOR_RECALL`."

        Design: Corner/errors/corner_recall_evaluation_requires_a_severe_member
        """
        world = _seed_three_mug_complaints(
            api, batch_code="LOT-MILD", reported_code="LOTMILD",
            descriptors=dict(complaint_type="FOREIGN_MATERIAL"),
        )
        for key in ("m1", "m2", "m3"):
            assert_severity(
                world["complaints"][key], adjudicated_score=40.00,
                adjudicated_band="S3",
            )
        lead = world.headers("ql1")
        signal = validate_success(
            api.create_trend_signal(
                {
                    "scope_level": "LOT",
                    "plant_id": world["plant"]["id"],
                    "production_line_id": world["line"]["id"],
                    "lot_id": world["lot"]["id"],
                    **LOT_WINDOW,
                },
                lead,
            ),
            201,
        )
        assert signal["membership_count"] == 3
        assert_two_decimal_value(signal["weighted_complaint_count"], 3.00)
        assert_two_decimal_value(signal["observed_rate_ppm"], 30.00)
        opened = open_investigation(api, world, signal["id"])
        assert opened["status"] == "INVESTIGATION_OPEN"

        refused = api.escalate_recall_evaluation(
            signal["id"], {"escalation_note": "Trying to escalate."}, lead
        )
        validate_error(refused, ApiErrorId.SEVERITY_TOO_LOW_FOR_RECALL, 422)

        still_investigating = validate_success(
            api.get_trend_signal(signal["id"], lead)
        )
        assert still_investigating["status"] == "INVESTIGATION_OPEN"
        _rows, meta = validate_paginated(
            api.list_signal_memberships(signal["id"], lead)
        )
        assert meta["total_count"] == 3


class TestActiveSignalPinsLotAndComplaints:
    def test_an_open_investigation_pins_the_lot_and_a_recall_pins_the_complaint(
        self, api
    ):
        """Two cross-entity guards fire from one signal at two different statuses.

        PRD: "A held lot returns `HOLD → RELEASED` only when no trend signal
        covering it sits in `INVESTIGATION_OPEN` or `RECALL_EVALUATION`; while one
        does, the attempt is refused with `ERR_SIGNAL_INVESTIGATION_ACTIVE`."

        Design: Corner/errors/corner_active_signal_blocks_lot_release_then_recall_blocks_hold_release
        """
        world = _seed_three_mug_complaints(
            api, batch_code="LOT-SHARP", reported_code="LOTSHARP",
            descriptors=SHARP_PACKAGING,
        )
        for key in ("m1", "m2", "m3"):
            assert_severity(
                world["complaints"][key], adjudicated_score=89.00,
                adjudicated_band="S2",
            )
        lead = world.headers("ql1")
        lot_id = world["lot"]["id"]
        held = validate_success(
            api.hold_production_lot(lot_id, {"reason": "Under review."}, lead)
        )
        assert held["release_status"] == "HOLD"
        signal = validate_success(
            api.create_trend_signal(
                {
                    "scope_level": "LOT",
                    "plant_id": world["plant"]["id"],
                    "production_line_id": world["line"]["id"],
                    "lot_id": lot_id,
                    **LOT_WINDOW,
                },
                lead,
            ),
            201,
        )
        assert signal["membership_count"] == 3
        assert_two_decimal_value(signal["weighted_complaint_count"], 6.00)
        open_investigation(api, world, signal["id"])
        member_id = world["complaints"]["m1"]["id"]

        pinned_lot = api.release_production_lot(
            lot_id, {"reason": "Trying to release."}, lead
        )
        validate_error(pinned_lot, ApiErrorId.SIGNAL_INVESTIGATION_ACTIVE, 409)

        frozen = validate_success(
            api.quality_hold_complaint(
                member_id, {"reason": "Hold pending the investigation."}, lead
            )
        )
        assert frozen["handling_status"] == "ON_QUALITY_HOLD"
        assert frozen["pre_hold_handling_status"] == "TRIAGED"

        escalated = escalate_to_recall_evaluation(
            api, world, signal["id"], escalation_note="Three S2 members."
        )
        assert escalated["status"] == "RECALL_EVALUATION"

        pinned_complaint = api.release_complaint_hold(
            member_id, {"reason": "Trying to release the hold."}, lead
        )
        validate_error(pinned_complaint, ApiErrorId.RECALL_EVALUATION_ACTIVE, 409)

        still_pinned_lot = api.release_production_lot(
            lot_id, {"reason": "Trying again."}, lead
        )
        validate_error(still_pinned_lot, ApiErrorId.SIGNAL_INVESTIGATION_ACTIVE, 409)


class TestRecallWaitsForFilings:
    def test_one_unfiled_reportable_member_blocks_the_recall_until_it_is_filed(
        self, api
    ):
        """The recall is refused, the second filing lands, the identical call passes.

        PRD: "A recall may not precede the regulatory filings it depends on:
        every member complaint whose `regulatory_status` is `REPORTABLE` must
        already have a report in `SUBMITTED`, failing which the initiation is
        refused with `ERR_REGULATORY_SUBMISSION_PENDING`."

        Design: Corner/errors/corner_recall_initiation_waits_for_regulatory_submissions
        """
        world = seed_base_world(
            api,
            actor_keys=("ag1", "sup1", "ql1", "ro1", "ro2"),
            create_lot=False,
        )
        add_lot(
            api, world, "lot1", batch_code="LOT-RECALL", units_produced=100000
        )
        world["lot"] = world["lots"]["lot1"]
        add_contact(
            api, world, "ct1", raw_message="Two people ill, both saw doctors."
        )
        reports = {}
        for key in ("m1", "m2"):
            complaint = validate_success(
                api.create_complaint(
                    complaint_payload(
                        world["contacts"]["ct1"]["id"],
                        reported_batch_code="LOTRECALL",
                        **ILLNESS_S1_COMPLAINT,
                    ),
                    world.headers("ag1"),
                ),
                201,
            )
            world["complaints"][key] = triage(api, world, complaint["id"])
            assert_severity(world["complaints"][key], effective_band="S1")
            reports[key] = find_report(api, world, complaint["id"])
            determine_report(
                api, world, reports[key]["id"], "REPORTABLE",
                determination_note="Reportable.",
            )
        filed = submit_report(
            api, world, reports["m1"]["id"], actor="ro2", agency_reference="AG-55001"
        )
        assert filed["status"] == "SUBMITTED"
        lead = world.headers("ql1")
        signal = validate_success(
            api.create_trend_signal(
                {
                    "scope_level": "LOT",
                    "plant_id": world["plant"]["id"],
                    "production_line_id": world["line"]["id"],
                    "lot_id": world["lot"]["id"],
                    **LOT_WINDOW,
                },
                lead,
            ),
            201,
        )
        assert_two_decimal_value(signal["weighted_complaint_count"], 6.00)
        open_investigation(api, world, signal["id"])
        escalate_to_recall_evaluation(
            api, world, signal["id"], escalation_note="Two S1 members."
        )

        blocked = api.initiate_recall(
            signal["id"], {"recall_reference": "RC-2026-01"}, lead
        )
        validate_error(blocked, ApiErrorId.REGULATORY_SUBMISSION_PENDING, 409)

        second_filing = submit_report(
            api, world, reports["m2"]["id"], actor="ro2", agency_reference="AG-55002"
        )
        assert second_filing["status"] == "SUBMITTED"
        assert second_filing["submitted_late"] is False

        recalled = validate_success(
            api.initiate_recall(
                signal["id"], {"recall_reference": "RC-2026-01"}, lead
            )
        )
        assert recalled["status"] == "RECALL_INITIATED"
        withdrawn = validate_success(
            api.get_production_lot(world["lot"]["id"], lead)
        )
        assert withdrawn["release_status"] == "WITHDRAWN"


# ---------------------------------------------------------------------------
# Sample-kit phase guard
# ---------------------------------------------------------------------------
class TestSampleKitPhaseGuard:
    def test_four_out_of_phase_kit_calls_are_refused_from_two_states(self, api):
        """Receive, lab-accept, a repeat dispatch and an early receive all bounce.

        PRD: "The kit's `status` permits the requested transition or custody
        append — otherwise `ERR_SAMPLE_KIT_STATE_INVALID` (409), including
        lockdown of the terminal `LAB_ACCEPTED`, `EXPIRED`, and `CANCELLED`
        states."

        Design: Corner/errors/corner_sample_kit_state_guard_rejects_out_of_phase_transitions
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
        seed_triaged_complaint(
            api, world, contact_overrides={"raw_message": "Soft matter."},
            **SOFT_FOREIGN_MATTER,
        )
        kit = add_kit(
            api, world, world["complaints"]["cp1"]["id"], "k1",
            kit_code="K-C01", seal_id_issued="SEAL-C01",
        )
        assert kit["status"] == "REQUESTED"
        kit_id = kit["id"]
        agent = world.headers("ag1")
        lead = world.headers("ql1")

        too_early_receive = api.receive_sample_kit(kit_id, {}, lead)
        validate_error(too_early_receive, ApiErrorId.SAMPLE_KIT_STATE_INVALID, 409)
        too_early_accept = api.lab_accept_sample_kit(
            kit_id, {"lab_note": "Too early."}, lead
        )
        validate_error(too_early_accept, ApiErrorId.SAMPLE_KIT_STATE_INVALID, 409)

        shipped = validate_success(api.ship_sample_kit(kit_id, {}, agent))
        assert shipped["status"] == "SHIPPED"
        assert shipped["custody_event_count"] == 1

        repeat_ship = api.ship_sample_kit(kit_id, {}, agent)
        validate_error(repeat_ship, ApiErrorId.SAMPLE_KIT_STATE_INVALID, 409)

        receive_before_pickup = api.receive_sample_kit(kit_id, {}, lead)
        validate_error(receive_before_pickup, ApiErrorId.SAMPLE_KIT_STATE_INVALID, 409)

        unmoved = validate_success(api.get_sample_kit(kit_id, agent))
        assert unmoved["status"] == "SHIPPED"
        assert unmoved["custody_event_count"] == 1
