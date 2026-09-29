"""Where the state machines start, which edges they refuse, and which of their
declared side effects fire when an edge is taken."""

from test_helpers import (
    ApiErrorId,
    add_complaint,
    add_contact,
    add_kit,
    add_lot,
    add_manual_signal,
    add_remedy,
    add_template,
    append_custody,
    assert_goodwill_ledger,
    assert_two_decimal_value,
    identify_product_payload,
    lab_accept_kit,
    open_investigation,
    receive_kit,
    respond,
    seed_base_world,
    seed_shipped_kit,
    set_clock,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

SHARP_PACKAGING_COMPLAINT = dict(
    complaint_type="PACKAGING",
    foreign_object_class="HARD_SHARP",
    medical_attention_sought=True,
    symptom_codes=["CUT", "PAIN", "SWELLING", "BLEEDING"],
)


class TestInitialStates:
    def test_seven_fresh_rows_sit_in_their_declared_initial_states(self, api):
        """Both complaint dimensions start independently in the same response.

        PRD: "`handling_status` is the care-workflow dimension and takes one of
        `INTAKE`, `TRIAGED`, `AWAITING_SAMPLE`, `IN_RESOLUTION`,
        `ON_QUALITY_HOLD`, `RESOLVED`, `CLOSED`, or `DUPLICATE`; it begins at
        `INTAKE` and `CLOSED` is terminal."

        Design: Corner/state_machines/corner_initial_states_on_creation_across_dimensions
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        assert world["lot"]["release_status"] == "RELEASED"

        contact = add_contact(api, world, "ct1", raw_message="Stale pack.")
        assert contact["status"] == "OPEN"

        complaint = add_complaint(api, world, "cp1", complaint_type="QUALITY")
        assert complaint["handling_status"] == "INTAKE"
        assert complaint["regulatory_status"] == "NOT_APPLICABLE"

        triage(api, world, complaint["id"])
        kit = add_kit(
            api, world, complaint["id"], "k1",
            kit_code="K-401", seal_id_issued="SEAL-401",
        )
        assert kit["status"] == "REQUESTED"
        assert kit["chain_integrity_status"] == "PENDING"
        assert kit["disposition"] == "PENDING"
        assert kit["custody_event_count"] == 0

        template = add_template(
            api, world, "tq",
            template_code="T-QUAL", applies_to_type="QUALITY",
            max_band_allowed="S4", activate=False,
        )
        assert template["status"] == "DRAFT"
        assert template["usage_count"] == 0

        remedy = add_remedy(
            api, world, complaint["id"], "rm1",
            remedy_type="COUPON", requested_value_cents=500,
        )
        assert remedy["status"] == "DRAFT"
        assert remedy["revision_count"] == 0
        assert remedy["base_value_cents"] == 500
        assert remedy["payout_cents"] == 500
        assert_two_decimal_value(remedy["uplift_pct"], 0.00)


class TestPreconditionsOnValidEdges:
    def test_close_no_complaint_succeeds_bare_and_is_refused_with_a_complaint(self, api):
        """One endpoint, two contacts, opposite outcomes decided by the child count.

        PRD: "Closing this way is only legitimate while `complaint_count` is
        still 0, and a contact that already carries a complaint is refused with
        `ERR_CONTACT_HAS_COMPLAINTS`."

        Design: Corner/state_machines/corner_contact_close_no_complaint_valid_transition_and_precondition
        """
        world = seed_base_world(api, actor_keys=("ag1",))
        bare = add_contact(
            api, world, "cta", channel="SOCIAL",
            raw_message="Just asking where to buy this.",
        )
        busy = add_contact(
            api, world, "ctb", channel="EMAIL", raw_message="Stale pack."
        )
        add_complaint(api, world, "cpb", contact_key="ctb", complaint_type="QUALITY")
        agent = world.headers("ag1")

        closed = validate_success(
            api.close_contact_no_complaint(
                bare["id"], {"reason": "Product-location enquiry only."}, agent
            )
        )
        assert closed["status"] == "CLOSED_NO_COMPLAINT"

        refused = api.close_contact_no_complaint(
            busy["id"],
            {"reason": "Trying to close a contact with a complaint."},
            agent,
        )
        validate_error(refused, ApiErrorId.CONTACT_HAS_COMPLAINTS, 409)

        # PRD 3.2: registering the complaint already moved the contact OPEN -> LOGGED.
        still_open = validate_success(api.get_contact(busy["id"], agent))
        assert still_open["status"] == "LOGGED"
        _rows, meta = validate_paginated(
            api.list_complaints(agent, {"contact_id": busy["id"]})
        )
        assert meta["total_count"] == 1

    def test_triage_waits_for_the_product_to_be_identified(self, api):
        """Identifying the product afterwards unblocks the very same call.

        PRD: "The complaint must be in `INTAKE`, and its
        `product_identification_status` must be `RESOLVED`; an unidentified
        complaint cannot be adjudicated at all, because both the regulated
        multiplier and the rate denominator would be unknown, and the attempt is
        refused with `ERR_PRODUCT_UNIDENTIFIED`."

        Design: Corner/state_machines/corner_triage_before_product_identification_is_refused
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_contact(api, world, "ct1", raw_message="I threw the packet away.")
        unidentified = validate_success(
            api.create_complaint(
                {
                    "contact_id": world["contacts"]["ct1"]["id"],
                    "complaint_type": "QUALITY",
                },
                world.headers("ag1"),
            ),
            201,
        )
        assert unidentified["product_identification_status"] == "UNRESOLVED"
        assert unidentified["lot_id"] is None

        refused = api.triage_complaint(
            unidentified["id"],
            {"reviewer_note": "Trying to triage an unidentified product."},
            world.headers("sup1"),
        )
        validate_error(refused, ApiErrorId.PRODUCT_UNIDENTIFIED, 409)
        blocked = validate_success(
            api.get_complaint(unidentified["id"], world.headers("sup1"))
        )
        assert blocked["handling_status"] == "INTAKE"

        identified = validate_success(
            api.identify_complaint_product(
                unidentified["id"],
                identify_product_payload("a1b/2026/0710"),
                world.headers("ag1"),
            )
        )
        assert identified["product_identification_status"] == "RESOLVED"
        assert identified["lot_id"] == world["lot"]["id"]

        triaged = triage(api, world, unidentified["id"], reviewer_note="Now identified.")
        assert triaged["handling_status"] == "TRIAGED"
        assert_two_decimal_value(triaged["adjudicated_severity_score"], 10.75)
        assert triaged["adjudicated_severity_band"] == "S4"


class TestSideEffectsOfOneTransition:
    def test_lab_acceptance_cascades_to_the_complaint_and_the_consumer(self, api):
        """Every declared consequence of acceptance is checked in one pass.

        PRD: "Acceptance sets `disposition` to `USABLE` when
        `chain_integrity_status` is `INTACT` and forces it to `UNUSABLE`
        otherwise, moves the parent complaint `AWAITING_SAMPLE →
        IN_RESOLUTION`, and lowers the consumer's `open_kit_count` by one."

        Design: Corner/state_machines/corner_lab_accept_side_effects_cascade_to_complaint_and_consumer
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
        add_contact(api, world, "ct1", raw_message="Soft foreign matter, I kept it.")
        add_complaint(
            api, world, "cp1",
            complaint_type="FOREIGN_MATERIAL", foreign_object_class="SOFT",
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        triage(api, world, complaint_id)
        seed_shipped_kit(
            api, world, complaint_id, "k1",
            kit_code="K-501", seal_id_issued="SEAL-501",
        )
        kit_id = world["kits"]["k1"]["id"]
        agent = world.headers("ag1")
        lead = world.headers("ql1")

        append_custody(
            api, world, kit_id, "CONSUMER_SEALED", "2026-08-01T12:00:00Z",
            actor_label="Rin Sato", seal_id_observed="SEAL-501",
        )
        append_custody(
            api, world, kit_id, "CARRIER_PICKUP", "2026-08-02T00:00:00Z",
            actor_label="Courier 88",
        )
        in_transit = validate_success(api.get_sample_kit(kit_id, agent))
        assert in_transit["status"] == "IN_TRANSIT_INBOUND"

        set_clock(api, "2026-08-06T00:00:00Z")
        append_custody(
            api, world, kit_id, "LAB_RECEIVED", "2026-08-06T00:00:00Z",
            actor="ql1", actor_label="Lab intake", seal_id_observed="SEAL-501",
        )
        received = receive_kit(api, world, kit_id)
        assert_two_decimal_value(received["transit_hours"], 96.00)
        assert received["chain_integrity_status"] == "PENDING"
        assert received["custody_event_count"] == 4

        append_custody(
            api, world, kit_id, "LAB_OPENED", "2026-08-06T02:00:00Z",
            actor="ql1", actor_label="Analyst 3",
        )
        complete = validate_success(api.get_sample_kit(kit_id, lead))
        assert complete["custody_event_count"] == 5
        assert complete["chain_integrity_status"] == "INTACT"

        accepted = lab_accept_kit(api, world, kit_id)
        assert accepted["status"] == "LAB_ACCEPTED"
        assert accepted["disposition"] == "USABLE"

        complaint = validate_success(api.get_complaint(complaint_id, agent))
        assert complaint["handling_status"] == "IN_RESOLUTION"
        consumer = validate_success(api.get_consumer(world["consumer"]["id"], agent))
        assert consumer["open_kit_count"] == 0

    def test_plant_posture_is_derived_from_its_signals_in_both_directions(self, api):
        """The plant row is never written directly, and the derivation reverses.

        PRD: "**Plant posture is never set directly.** `oversight_posture` is
        re-derived from the plant's own population of trend signals after every
        signal transition and during every operations checkpoint, to a fixed
        point, in the same request."

        Design: Corner/state_machines/corner_plant_oversight_posture_is_derived_and_re_derived
        """
        world = _seed_manual_signal_on_a_sharp_edge_report(api, "LOT-P", "lotp")
        lead = world.headers("ql1")
        assert world["plant"]["oversight_posture"] == "NORMAL"
        assert world["plant"]["open_investigation_count"] == 0
        assert world["signals"]["sig1"]["membership_count"] == 1
        assert_two_decimal_value(
            world["signals"]["sig1"]["weighted_complaint_count"], 2.00
        )

        opened = open_investigation(api, world, world["signals"]["sig1"]["id"])
        assert opened["status"] == "INVESTIGATION_OPEN"
        watching = validate_success(api.get_plant(world["plant"]["id"], lead))
        assert watching["open_investigation_count"] == 1
        assert watching["oversight_posture"] == "WATCH"

        closed = validate_success(
            api.close_signal_no_action(
                world["signals"]["sig1"]["id"],
                {"closing_note": "One-off defect, no systemic issue."},
                lead,
            )
        )
        assert closed["status"] == "CLOSED_NO_ACTION"
        back_to_normal = validate_success(api.get_plant(world["plant"]["id"], lead))
        assert back_to_normal["open_investigation_count"] == 0
        assert back_to_normal["oversight_posture"] == "NORMAL"


def _seed_manual_signal_on_a_sharp_edge_report(api, batch_code, lot_key):
    """One S2 packaging complaint on an unregulated lot, under a manual signal."""
    world = seed_base_world(
        api, actor_keys=("ag1", "ql1"), product="mug", create_lot=False
    )
    add_lot(
        api, world, lot_key, product_key="mug", batch_code=batch_code,
        code_date="2026-07-10T00:00:00Z", units_produced=100000,
    )
    add_contact(api, world, "ct1", channel="WEB", raw_message="Sharp edge on the mug.")
    add_complaint(
        api, world, "cp1",
        reported_batch_code=batch_code.replace("-", ""),
        **SHARP_PACKAGING_COMPLAINT,
    )
    add_manual_signal(
        api, world, "sig1", lot_key=lot_key,
        window_start="2026-07-20T00:00:00Z", window_end="2026-08-02T00:00:00Z",
    )
    return world


class TestInvalidEdgesAndTerminalStates:
    def test_three_later_transitions_are_all_refused_from_intake(self, api):
        """The guard is a whitelist per from-state, not a single terminal check.

        PRD: "The complaint's `handling_status` permits the requested handling
        transition — otherwise `ERR_COMPLAINT_STATE_INVALID` (409), including any
        attempt to move out of terminal `CLOSED`."

        Design: Corner/state_machines/corner_complaint_close_from_intake_is_an_invalid_transition
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
        add_contact(api, world, "ct1", raw_message="Stale pack.")
        created = add_complaint(api, world, "cp1", complaint_type="QUALITY")

        refusals = [
            api.close_complaint(
                created["id"],
                {"closing_note": "Closing straight from intake."},
                world.headers("sup1"),
            ),
            api.resolve_complaint(
                created["id"],
                {"resolution_note": "Resolving straight from intake."},
                world.headers("ag1"),
            ),
            api.release_complaint_hold(
                created["id"],
                {"reason": "Releasing a hold that never existed."},
                world.headers("ql1"),
            ),
        ]
        for response in refusals:
            validate_error(response, ApiErrorId.COMPLAINT_STATE_INVALID, 409)

        unchanged = validate_success(
            api.get_complaint(created["id"], world.headers("sup1"))
        )
        assert unchanged["handling_status"] == "INTAKE"
        assert unchanged["version"] == created["version"]

    def test_a_closed_complaint_refuses_even_a_second_close(self, api):
        """Re-closing is an error rather than an idempotent success.

        PRD: "It moves the complaint `RESOLVED → CLOSED`, which is terminal in
        the handling dimension and after which no handling transition of any kind
        is permitted."

        Design: Corner/state_machines/corner_closed_complaint_is_locked_down
        """
        world = _seed_closed_quality_complaint(api)
        complaint_id = world["complaints"]["cp1"]["id"]
        supervisor = world.headers("sup1")

        for response, expected, status in (
            (
                api.close_complaint(
                    complaint_id, {"closing_note": "Closing again."}, supervisor
                ),
                ApiErrorId.COMPLAINT_STATE_INVALID,
                409,
            ),
            (
                api.triage_complaint(
                    complaint_id, {"reviewer_note": "Re-triage."}, supervisor
                ),
                ApiErrorId.COMPLAINT_STATE_INVALID,
                409,
            ),
            (
                api.quality_hold_complaint(
                    complaint_id, {"reason": "Late hold."}, world.headers("ql1")
                ),
                ApiErrorId.COMPLAINT_STATE_INVALID,
                409,
            ),
            (
                api.mark_complaint_duplicate(
                    complaint_id,
                    {"duplicate_of_complaint_id": complaint_id},
                    supervisor,
                ),
                ApiErrorId.DUPLICATE_TARGET_INVALID,
                422,
            ),
        ):
            validate_error(response, expected, status)

        locked = validate_success(api.get_complaint(complaint_id, supervisor))
        assert locked["handling_status"] == "CLOSED"
        assert locked["regulatory_status"] == "NOT_APPLICABLE"

    def test_a_withdrawn_lot_refuses_release_hold_and_a_second_withdrawal(self, api):
        """The cycle works right up to the terminal edge, and then nothing moves.

        PRD: "A lot cannot be withdrawn directly from `RELEASED`, and nothing
        moves out of `WITHDRAWN`; either attempt yields
        `ERR_LOT_STATE_INVALID`."

        Design: Corner/state_machines/corner_withdrawn_lot_is_locked_down
        """
        world = seed_base_world(api, actor_keys=("ql1",))
        lot_id = world["lot"]["id"]
        lead = world.headers("ql1")

        held = validate_success(
            api.hold_production_lot(lot_id, {"reason": "Review."}, lead)
        )
        assert held["release_status"] == "HOLD"
        released = validate_success(
            api.release_production_lot(lot_id, {"reason": "Cleared."}, lead)
        )
        assert released["release_status"] == "RELEASED"
        validate_success(
            api.hold_production_lot(lot_id, {"reason": "Second review."}, lead)
        )
        withdrawn = validate_success(
            api.withdraw_production_lot(lot_id, {"reason": "Pulled from trade."}, lead)
        )
        assert withdrawn["release_status"] == "WITHDRAWN"

        for response in (
            api.release_production_lot(lot_id, {"reason": "Un-withdrawing."}, lead),
            api.withdraw_production_lot(lot_id, {"reason": "Withdrawing again."}, lead),
            api.hold_production_lot(
                lot_id, {"reason": "Holding a withdrawn lot."}, lead
            ),
        ):
            validate_error(response, ApiErrorId.LOT_STATE_INVALID, 409)

        assert (
            validate_success(api.get_production_lot(lot_id, lead))["release_status"]
            == "WITHDRAWN"
        )

    def test_activating_an_active_or_retired_template_is_refused(self, api):
        """The template machine is linear, so re-firing an applied edge errors.

        PRD: "Activating or retiring a template whose `status` does not permit
        that step yields `ERR_TEMPLATE_STATE_INVALID`."

        Design: Corner/state_machines/corner_second_activate_on_active_template_is_rejected
        """
        world = seed_base_world(api, actor_keys=("sup1",), create_lot=False)
        supervisor = world.headers("sup1")
        drafted = add_template(
            api, world, "t1", template_code="T-ANY", applies_to_type="ANY",
            max_band_allowed="S2", activate=False,
        )
        assert drafted["status"] == "DRAFT"

        activated = validate_success(
            api.activate_response_template(drafted["id"], {}, supervisor)
        )
        assert activated["status"] == "ACTIVE"

        again = api.activate_response_template(drafted["id"], {}, supervisor)
        validate_error(again, ApiErrorId.TEMPLATE_STATE_INVALID, 409)
        assert (
            validate_success(api.get_response_template(drafted["id"], supervisor))[
                "status"
            ]
            == "ACTIVE"
        )

        retired = validate_success(
            api.retire_response_template(
                drafted["id"], {"reason": "Superseded."}, supervisor
            )
        )
        assert retired["status"] == "RETIRED"
        assert retired["usage_count"] == 0

        after_retirement = api.activate_response_template(drafted["id"], {}, supervisor)
        validate_error(after_retirement, ApiErrorId.TEMPLATE_STATE_INVALID, 409)

    def test_dismissing_a_signal_forecloses_every_other_detected_edge(self, api):
        """Taking one fork of a branching machine closes the other permanently.

        PRD: "Any transition attempted from a signal `status` that does not
        permit it yields `ERR_TREND_SIGNAL_STATE_INVALID`."

        Design: Corner/state_machines/corner_trend_signal_dismiss_fork_excludes_the_investigation_fork
        """
        world = _seed_manual_signal_on_a_sharp_edge_report(api, "LOT-F", "lotf")
        signal_id = world["signals"]["sig1"]["id"]
        lead = world.headers("ql1")
        assert world["signals"]["sig1"]["status"] == "DETECTED"

        dismissed = validate_success(
            api.dismiss_trend_signal(
                signal_id, {"reason": "Single isolated report."}, lead
            )
        )
        assert dismissed["status"] == "DISMISSED"

        for response in (
            api.open_signal_investigation(
                signal_id, {"investigation_note": "Changed my mind."}, lead
            ),
            api.dismiss_trend_signal(signal_id, {"reason": "Dismissing twice."}, lead),
            api.escalate_recall_evaluation(
                signal_id,
                {"escalation_note": "Skipping the investigation step."},
                lead,
            ),
            api.initiate_recall(signal_id, {"recall_reference": "RC-0001"}, lead),
        ):
            error = validate_error(response, ApiErrorId.TREND_SIGNAL_STATE_INVALID, 409)
            assert error["error_id"] != ApiErrorId.SEVERITY_TOO_LOW_FOR_RECALL

        assert (
            validate_success(api.get_trend_signal(signal_id, lead))["status"]
            == "DISMISSED"
        )
        assert (
            validate_success(api.get_plant(world["plant"]["id"], lead))[
                "open_investigation_count"
            ]
            == 0
        )


def _seed_closed_quality_complaint(api):
    """A mild quality complaint driven all the way to CLOSED."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
    add_template(
        api, world, "tq", template_code="T-QUAL", applies_to_type="QUALITY",
        max_band_allowed="S4",
    )
    add_contact(api, world, "ct1", channel="EMAIL", raw_message="Stale pack.")
    add_complaint(api, world, "cp1", complaint_type="QUALITY")
    complaint_id = world["complaints"]["cp1"]["id"]
    triage(api, world, complaint_id, reviewer_note="Mild.")
    respond(api, world, complaint_id, world["templates"]["tq"]["id"])
    validate_success(
        api.resolve_complaint(
            complaint_id, {"resolution_note": "Consumer satisfied."},
            world.headers("ag1"),
        )
    )
    closed = validate_success(
        api.close_complaint(
            complaint_id, {"closing_note": "Closed."}, world.headers("sup1")
        )
    )
    assert closed["handling_status"] == "CLOSED"
    world["complaints"]["cp1"] = closed
    return world


class TestCyclicEdges:
    def test_a_quality_hold_round_trip_restores_the_pre_hold_status(self, api):
        """The departing state is stored on the way in and cleared on the way out.

        PRD: "Releasing the hold, again a `QualityLead` action with an optional
        `reason`, returns the complaint from `ON_QUALITY_HOLD` to exactly the
        state recorded in `pre_hold_handling_status` and then clears that
        field."

        Design: Corner/state_machines/corner_quality_hold_round_trip_restores_pre_hold_status
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
        add_contact(api, world, "ct1", raw_message="Soft matter in the pack.")
        add_complaint(
            api, world, "cp1",
            complaint_type="FOREIGN_MATERIAL", foreign_object_class="SOFT",
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        triage(api, world, complaint_id, reviewer_note="Retrieve.")
        add_kit(
            api, world, complaint_id, "k1",
            kit_code="K-601", seal_id_issued="SEAL-601",
        )
        validate_success(
            api.cancel_sample_kit(
                world["kits"]["k1"]["id"],
                {"reason": "Consumer discarded it."},
                world.headers("sup1"),
            )
        )
        lead = world.headers("ql1")
        assert (
            validate_success(api.get_complaint(complaint_id, lead))["handling_status"]
            == "IN_RESOLUTION"
        )

        held = validate_success(
            api.quality_hold_complaint(
                complaint_id, {"reason": "Batch under review."}, lead
            )
        )
        assert held["handling_status"] == "ON_QUALITY_HOLD"
        assert held["pre_hold_handling_status"] == "IN_RESOLUTION"

        released = validate_success(
            api.release_complaint_hold(
                complaint_id, {"reason": "Review closed."}, lead
            )
        )
        assert released["handling_status"] == "IN_RESOLUTION"
        assert released["pre_hold_handling_status"] is None

        _remedies, meta = validate_paginated(
            api.list_remedies(lead, {"complaint_id": complaint_id})
        )
        assert meta["total_count"] == 0
        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(consumer, authorized=0, outstanding=0, paid=0, voided=0)
