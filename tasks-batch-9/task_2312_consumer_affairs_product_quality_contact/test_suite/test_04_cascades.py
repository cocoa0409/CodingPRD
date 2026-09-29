"""Single writes whose consequences travel two and three entities outward."""

from test_helpers import (
    CLOCK_EPOCH,
    CLOCK_EPOCH_MS,
    ILLNESS_S1_COMPLAINT,
    PACKAGING_S2_COMPLAINT,
    ApiErrorId,
    add_complaint,
    add_contact,
    add_lot,
    assert_goodwill_ledger,
    assert_lot_buckets,
    assert_severity,
    assert_two_decimal_value,
    escalate_to_recall_evaluation,
    find_report,
    open_investigation,
    production_lot_payload,
    run_quality_ops,
    seed_approved_remedy,
    seed_base_world,
    seed_firing_lot_scope,
    set_clock,
    shift,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Recall escalation: signal to complaints to remedies to plant freeze
# ---------------------------------------------------------------------------
def _seed_investigated_lot_signal(api):
    """A firing lot signal under investigation, with one approved remedy behind it."""
    world = seed_base_world(
        api, actor_keys=("ag1", "sup1", "ql1"), product="mug", create_lot=False
    )
    add_lot(
        api,
        world,
        "lotb",
        product_key="mug",
        batch_code="LOT-B",
        code_date="2026-07-10T00:00:00Z",
        units_produced=100000,
    )
    add_contact(api, world, "ct1")
    seed_firing_lot_scope(
        api,
        world,
        complaint_template=dict(PACKAGING_S2_COMPLAINT, reported_batch_code="LOTB"),
        count=3,
    )
    seed_approved_remedy(
        api,
        world,
        world["complaints"]["cp1"]["id"],
        "rm1",
        remedy_type="COUPON",
        requested_value_cents=2000,
    )
    set_clock(api, "2026-08-02T00:00:00Z")
    run_quality_ops(api, world, dry_run=False)
    signals, meta = validate_paginated(
        api.list_trend_signals(
            world.headers("ql1"), {"lot_id": world["lots"]["lotb"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "the operations checkpoint did not raise the signal"
    world["signals"]["sig1"] = open_investigation(api, world, signals[0]["id"])
    return world


class TestRecallEscalationCascade:
    def test_escalation_holds_every_member_complaint_and_voids_its_goodwill(self, api):
        """The three members freeze and the approved coupon lands in the voided bucket.

        PRD: "Every member complaint not already in `RESOLVED`, `CLOSED`, or
        `DUPLICATE` is moved to `ON_QUALITY_HOLD`, recording its departing state
        in `pre_hold_handling_status` and voiding its live remedies with the
        consumer goodwill ledger reconciled exactly as in §3.6."

        Design: Difficulty/transitive_cascade/recall_escalation_cascades_signal_to_complaints_to_remedies_to_plant_freeze
        """
        world = _seed_investigated_lot_signal(api)

        escalated = escalate_to_recall_evaluation(
            api, world, world["signals"]["sig1"]["id"]
        )
        assert escalated["status"] == "RECALL_EVALUATION"

        for key in ("cp1", "cp2", "cp3"):
            complaint = validate_success(
                api.get_complaint(world["complaints"][key]["id"], world.headers("sup1"))
            )
            assert complaint["handling_status"] == "ON_QUALITY_HOLD"
            assert complaint["pre_hold_handling_status"] == "TRIAGED"

        remedy = validate_success(
            api.get_remedy(world["remedies"]["rm1"]["id"], world.headers("sup1"))
        )
        assert remedy["status"] == "VOIDED_BY_HOLD"

        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(
            consumer, authorized=2200, outstanding=0, paid=0, voided=2200
        )

    def test_escalation_holds_the_lot_in_scope(self, api):
        """The single named lot of a lot-scope signal moves off release.

        PRD: "Every lot in scope is placed on hold: for a `LOT`-scope signal
        that is the single named lot, and for `LINE`- and `PLANT`-scope signals
        it is every lot in scope currently in `RELEASED`, each moving `RELEASED
        → HOLD`."

        Design: Difficulty/transitive_cascade/recall_escalation_cascades_signal_to_complaints_to_remedies_to_plant_freeze
        """
        world = _seed_investigated_lot_signal(api)
        before = validate_success(
            api.get_production_lot(world["lots"]["lotb"]["id"], world.headers("ql1"))
        )
        assert before["release_status"] == "RELEASED"

        escalate_to_recall_evaluation(api, world, world["signals"]["sig1"]["id"])

        after = validate_success(
            api.get_production_lot(world["lots"]["lotb"]["id"], world.headers("ql1"))
        )
        assert after["release_status"] == "HOLD"

    def test_escalation_freezes_the_plant_and_blocks_new_lot_registration(self, api):
        """A watched plant is forced to investigation hold and refuses new lots.

        PRD: "The plant's `oversight_posture` is then forced to
        `INVESTIGATION_HOLD`, which is what blocks new lot registration for that
        plant's lines."

        Design: Difficulty/transitive_cascade/recall_escalation_cascades_signal_to_complaints_to_remedies_to_plant_freeze
        """
        world = _seed_investigated_lot_signal(api)
        watched = validate_success(
            api.get_plant(world["plant"]["id"], world.headers("ql1"))
        )
        assert watched["oversight_posture"] == "WATCH"

        escalate_to_recall_evaluation(api, world, world["signals"]["sig1"]["id"])

        frozen = validate_success(
            api.get_plant(world["plant"]["id"], world.headers("ql1"))
        )
        assert frozen["oversight_posture"] == "INVESTIGATION_HOLD"

        refused = api.create_production_lot(
            production_lot_payload(
                world["products"]["mug"]["id"],
                world["lines"]["l1"]["id"],
                batch_code="LOT-Z",
                code_date="2026-07-20T00:00:00Z",
                units_produced=50000,
            ),
            world.headers("ql1"),
        )
        validate_error(refused, ApiErrorId.PLANT_UNDER_INVESTIGATION_HOLD, 409)
        _rows, meta = validate_paginated(
            api.list_production_lots(world.headers("ql1"))
        )
        assert meta["total_count"] == 1, "the refused registration wrote a lot anyway"


# ---------------------------------------------------------------------------
# An S1 adjudication: band to lot hold to report deadline to sentiment
# ---------------------------------------------------------------------------
def _seed_untriaged_illness(api):
    world = seed_base_world(api, actor_keys=("ag1", "sup1", "ro1"))
    add_contact(api, world, "ct1")
    add_complaint(api, world, "cp1", **ILLNESS_S1_COMPLAINT)
    return world


class TestSeverityOneTriageCascade:
    def test_severe_adjudication_holds_the_lot_and_shifts_its_buckets(self, api):
        """The lot leaves release on the strength of a single S1 adjudication.

        PRD: "When the adjudicated band is `S1`, the linked lot is additionally
        moved `RELEASED → HOLD`."

        Design: Difficulty/transitive_cascade/s1_triage_cascades_band_to_lot_hold_to_report_deadline_to_sentiment
        """
        world = _seed_untriaged_illness(api)
        before = validate_success(
            api.get_production_lot(world["lot"]["id"], world.headers("sup1"))
        )
        assert before["release_status"] == "RELEASED"
        assert_lot_buckets(before, linked=1, provisional=1, adjudicated=0, duplicate=0)

        adjudicated = validate_success(
            api.triage_complaint(
                world["complaints"]["cp1"]["id"],
                {"reviewer_note": "Severe."},
                world.headers("sup1"),
            )
        )
        assert_severity(
            adjudicated,
            provisional_score=87.00,
            provisional_band="S2",
            adjudicated_score=93.53,
            adjudicated_band="S1",
            effective_band="S1",
        )

        after = validate_success(
            api.get_production_lot(world["lot"]["id"], world.headers("sup1"))
        )
        assert after["release_status"] == "HOLD"
        assert_lot_buckets(after, linked=1, provisional=0, adjudicated=1, duplicate=0)

    def test_severe_adjudication_opens_a_report_on_the_short_deadline(self, api):
        """One report opens at the clock and falls due 24 hours later, not 72.

        PRD: "`due_at` is 24 hours after `escalated_at` when the band is `S1`,
        and 72 hours after `escalated_at` for every other band."

        Design: Difficulty/transitive_cascade/s1_triage_cascades_band_to_lot_hold_to_report_deadline_to_sentiment
        """
        world = _seed_untriaged_illness(api)

        adjudicated = validate_success(
            api.triage_complaint(
                world["complaints"]["cp1"]["id"],
                {"reviewer_note": "Severe."},
                world.headers("sup1"),
            )
        )
        assert adjudicated["handling_status"] == "TRIAGED"
        assert adjudicated["regulatory_status"] == "ESCALATED"

        reports, meta = validate_paginated(
            api.list_regulatory_reports(
                world.headers("ro1"), {"complaint_id": adjudicated["id"]}
            )
        )
        assert meta["total_count"] == 1
        report = reports[0]
        assert report["status"] == "OPEN"
        assert report["escalated_at"] == CLOCK_EPOCH_MS
        assert report["due_at"] == shift(CLOCK_EPOCH, hours=24)
        assert report["due_at"] != shift(CLOCK_EPOCH, hours=72)

    def test_severe_adjudication_deepens_the_sentiment_penalty(self, api):
        """The S2 penalty plus the unadjudicated surcharge gives way to the S1 penalty.

        PRD: "The index starts from a neutral base of 50. Every complaint of
        that consumer that is not in `DUPLICATE` and whose `created_at` is no
        earlier than 180 days before the logical clock counts as in-window and
        contributes a penalty: 20 points for an `effective_severity_band` of
        `S1`, 12 for `S2`, 6 for `S3`, and 3 for `S4`, plus a surcharge of 5
        further points whenever the complaint still has no
        `adjudicated_severity_score`."

        Design: Difficulty/transitive_cascade/s1_triage_cascades_band_to_lot_hold_to_report_deadline_to_sentiment
        """
        world = _seed_untriaged_illness(api)
        supervisor = world.headers("sup1")

        before = validate_success(
            api.get_consumer_sentiment(world["consumer"]["id"], supervisor)
        )
        assert_two_decimal_value(before["penalty_total"], 17.00)
        assert_two_decimal_value(before["sentiment_index"], 33.00)

        validate_success(
            api.triage_complaint(
                world["complaints"]["cp1"]["id"],
                {"reviewer_note": "Severe."},
                supervisor,
            )
        )

        after = validate_success(
            api.get_consumer_sentiment(world["consumer"]["id"], supervisor)
        )
        assert_two_decimal_value(after["penalty_total"], 20.00)
        assert_two_decimal_value(after["sentiment_index"], 30.00)
        assert after["complaint_count_in_window"] == 1

    def test_report_deadline_and_lot_hold_are_visible_together(self, api):
        """The regulatory dimension and the supply-chain hold both follow one write.

        PRD: "When the adjudicated band is `S1` or `S2` **and** the
        `complaint_type` is `ILLNESS` or `FOREIGN_MATERIAL`, a regulatory report
        is created automatically in `OPEN` with its `escalated_at` set to the
        logical clock and its `due_at` derived from the band, and the
        complaint's `regulatory_status` advances `NOT_APPLICABLE → ESCALATED`."

        Design: Difficulty/transitive_cascade/s1_triage_cascades_band_to_lot_hold_to_report_deadline_to_sentiment
        """
        world = _seed_untriaged_illness(api)

        validate_success(
            api.triage_complaint(
                world["complaints"]["cp1"]["id"],
                {"reviewer_note": "Severe."},
                world.headers("sup1"),
            )
        )

        report = find_report(api, world, world["complaints"]["cp1"]["id"])
        assert report["status"] == "OPEN"
        lot = validate_success(
            api.get_production_lot(world["lot"]["id"], world.headers("sup1"))
        )
        assert lot["release_status"] == "HOLD"
