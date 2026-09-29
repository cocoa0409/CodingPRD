"""Guards probed at the exact instant, position or bound where they begin to
bite — and, in one case, the whole fiscal ladder satisfied at once so the
approval goes through."""

from test_helpers import (
    CLOCK_EPOCH,
    CLOCK_EPOCH_MS,
    ApiErrorId,
    add_complaint,
    add_consumer,
    add_contact,
    add_kit,
    add_lot,
    add_remedy,
    add_template,
    append_custody,
    assert_goodwill_ledger,
    assert_goodwill_math,
    assert_severity,
    contact_payload,
    custody_event_payload,
    mark_duplicate_payload,
    respond_payload,
    seed_base_world,
    seed_shipped_kit,
    seed_triaged_complaint,
    submit_remedy,
    trend_signal_payload,
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


# ---------------------------------------------------------------------------
# Temporal guards on intake and on the custody chain
# ---------------------------------------------------------------------------
class TestTemporalGuards:
    def test_intake_may_be_logged_at_the_clock_but_not_after_it(self, api):
        """One millisecond ahead of the clock is refused; the clock itself is fine.

        PRD: "On `POST /contacts`, `received_at` is not after the logical clock —
        otherwise `ERR_RECEIVED_AT_IN_FUTURE` (422)."

        Design: Corner/validations/corner_contact_received_at_may_equal_the_clock_but_not_exceed_it
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        consumer_id = world["consumer"]["id"]
        agent = world.headers("ag1")

        ahead = api.create_contact(
            contact_payload(
                consumer_id,
                received_at="2026-08-01T00:00:00.001Z",
                raw_message="One millisecond in the future.",
            ),
            agent,
        )
        validate_error(ahead, ApiErrorId.RECEIVED_AT_IN_FUTURE, 422)

        exactly_now = validate_success(
            api.create_contact(
                contact_payload(
                    consumer_id, received_at=CLOCK_EPOCH, raw_message="Exactly now."
                ),
                agent,
            ),
            201,
        )
        assert exactly_now["status"] == "OPEN"

        backdated = validate_success(
            api.create_contact(
                contact_payload(
                    consumer_id,
                    channel="EMAIL",
                    received_at="2026-07-15T09:30:00Z",
                    raw_message="Backdated intake.",
                ),
                agent,
            ),
            201,
        )
        assert backdated["received_at"] == "2026-07-15T09:30:00.000Z"

        _rows, meta = validate_paginated(
            api.list_contacts(agent, {"consumer_id": consumer_id})
        )
        assert meta["total_count"] == 2

    def test_a_custody_step_may_tie_the_previous_instant_but_not_precede_it(self, api):
        """A second early is refused and costs no version; the same instant is kept.

        PRD: "On `POST /sample-kits/{id}/custody-events`, the appended
        `occurred_at` is not earlier than the previous event's `occurred_at` —
        otherwise `ERR_CUSTODY_OUT_OF_ORDER` (422)."

        Design: Corner/validations/corner_custody_event_occurred_at_may_tie_but_not_regress
        """
        world = _seed_sealed_kit(api, kit_code="K-901", seal="SEAL-901")
        kit_id = world["kits"]["k1"]["id"]
        agent = world.headers("ag1")
        before = validate_success(api.get_sample_kit(kit_id, agent))
        assert before["custody_event_count"] == 2

        regressed = api.append_custody_event(
            kit_id,
            custody_event_payload(
                "CARRIER_PICKUP",
                "2026-08-02T11:59:59Z",
                before["version"],
                actor_label="Courier 88",
            ),
            agent,
        )
        validate_error(regressed, ApiErrorId.CUSTODY_OUT_OF_ORDER, 422)

        untouched = validate_success(api.get_sample_kit(kit_id, agent))
        assert untouched["custody_event_count"] == 2
        assert untouched["version"] == before["version"]

        tied = validate_success(
            api.append_custody_event(
                kit_id,
                custody_event_payload(
                    "CARRIER_PICKUP",
                    "2026-08-02T12:00:00Z",
                    before["version"],
                    actor_label="Courier 88",
                ),
                agent,
            ),
            201,
        )
        assert tied["sequence_no"] == 3

        _events, meta = validate_paginated(api.list_custody_events(kit_id, agent))
        assert meta["total_count"] == 3
        moving = validate_success(api.get_sample_kit(kit_id, agent))
        assert moving["status"] == "IN_TRANSIT_INBOUND"

    def test_a_custody_step_must_be_the_one_the_sequence_expects_next(self, api):
        """Skipping ahead and repeating a consumed step both fail on shape alone.

        PRD: "The chain must follow exactly five steps in exactly this order:
        `KIT_ISSUED`, `CONSUMER_SEALED`, `CARRIER_PICKUP`, `LAB_RECEIVED`,
        `LAB_OPENED`. An `event_type` that is not the one expected at the next
        position is refused with `ERR_CUSTODY_SEQUENCE_INVALID`, and an
        `occurred_at` earlier than the previous event's `occurred_at` is refused
        with `ERR_CUSTODY_OUT_OF_ORDER`."

        Design: Corner/validations/corner_custody_event_type_must_match_the_next_required_position
        """
        world = seed_base_world(
            api, clock="2026-08-02T00:00:00Z", actor_keys=("ag1", "sup1")
        )
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"received_at": CLOCK_EPOCH, "raw_message": "Soft matter."},
            **SOFT_FOREIGN_MATTER,
        )
        seed_shipped_kit(
            api, world, world["complaints"]["cp1"]["id"], "k1",
            kit_code="K-902", seal_id_issued="SEAL-902",
        )
        kit_id = world["kits"]["k1"]["id"]
        agent = world.headers("ag1")
        shipped = validate_success(api.get_sample_kit(kit_id, agent))
        assert shipped["custody_event_count"] == 1
        pinned_version = shipped["version"]

        skipped_ahead = api.append_custody_event(
            kit_id,
            custody_event_payload(
                "LAB_RECEIVED", "2026-08-02T00:00:00Z", pinned_version,
                actor_label="Lab intake", seal_id_observed="SEAL-902",
            ),
            agent,
        )
        validate_error(skipped_ahead, ApiErrorId.CUSTODY_SEQUENCE_INVALID, 422)

        repeated = api.append_custody_event(
            kit_id,
            custody_event_payload(
                "KIT_ISSUED", "2026-08-02T00:00:00Z", pinned_version,
                actor_label="Ada Grant",
            ),
            agent,
        )
        validate_error(repeated, ApiErrorId.CUSTODY_SEQUENCE_INVALID, 422)

        expected_next = validate_success(
            api.append_custody_event(
                kit_id,
                custody_event_payload(
                    "CONSUMER_SEALED", "2026-08-02T12:00:00Z", pinned_version,
                    actor_label="Rin Sato", seal_id_observed="SEAL-902",
                ),
                agent,
            ),
            201,
        )
        assert expected_next["sequence_no"] == 2


def _seed_sealed_kit(api, *, kit_code, seal):
    """A shipped kit whose consumer-sealed step is already on the chain."""
    world = seed_base_world(
        api, clock="2026-08-02T00:00:00Z", actor_keys=("ag1", "sup1")
    )
    seed_triaged_complaint(
        api,
        world,
        contact_overrides={"received_at": CLOCK_EPOCH, "raw_message": "Soft matter."},
        **SOFT_FOREIGN_MATTER,
    )
    seed_shipped_kit(
        api, world, world["complaints"]["cp1"]["id"], "k1",
        kit_code=kit_code, seal_id_issued=seal,
    )
    append_custody(
        api, world, world["kits"]["k1"]["id"], "CONSUMER_SEALED",
        "2026-08-02T12:00:00Z", actor_label="Rin Sato", seal_id_observed=seal,
    )
    return world


# ---------------------------------------------------------------------------
# Referential guards
# ---------------------------------------------------------------------------
class TestDuplicateTargets:
    def test_only_a_sibling_that_is_not_itself_a_duplicate_may_be_targeted(self, api):
        """Self, a stranger's complaint and a duplicate all draw the same refusal.

        PRD: "On `POST /complaints/{id}/mark-duplicate`, the duplicate target
        belongs to the same consumer and is not itself in `DUPLICATE` — otherwise
        `ERR_DUPLICATE_TARGET_INVALID` (422). Duplicate chains are one level deep
        and never cross consumers."

        Design: Corner/validations/corner_duplicate_target_must_be_a_sibling_and_not_itself_duplicate
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_consumer(
            api, world, "c2", external_ref="C-2", full_name="Ola Berg",
            postal_code="60602",
        )
        add_contact(api, world, "cta", raw_message="Same issue, three calls.")
        add_contact(
            api, world, "ctb", consumer_key="c2", raw_message="Different household."
        )
        for key in ("p1", "p2", "p3"):
            add_complaint(api, world, key, contact_key="cta")
        add_complaint(api, world, "q1", contact_key="ctb")
        supervisor = world.headers("sup1")
        primary = world["complaints"]["p1"]["id"]
        already_duplicate = world["complaints"]["p2"]["id"]
        subject = world["complaints"]["p3"]["id"]

        validate_success(
            api.mark_complaint_duplicate(
                already_duplicate, mark_duplicate_payload(primary), supervisor
            )
        )

        for target in (subject, world["complaints"]["q1"]["id"], already_duplicate):
            refused = api.mark_complaint_duplicate(
                subject, mark_duplicate_payload(target), supervisor
            )
            validate_error(refused, ApiErrorId.DUPLICATE_TARGET_INVALID, 422)

        accepted = validate_success(
            api.mark_complaint_duplicate(
                subject, mark_duplicate_payload(primary), supervisor
            )
        )
        assert accepted["handling_status"] == "DUPLICATE"
        assert accepted["duplicate_of_complaint_id"] == primary

        _rows, meta = validate_paginated(
            api.list_complaints(
                world.headers("ag1"), {"duplicate_of_complaint_id": primary}
            )
        )
        assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Trend-signal shape and window guards
# ---------------------------------------------------------------------------
def _seed_plant_with_one_sharp_edge_report(api, *, clock, batch_code, reported_code):
    """An unregulated lot carrying a single packaging complaint."""
    world = seed_base_world(
        api,
        clock=clock,
        actor_keys=("ag1", "ql1"),
        product="mug",
        create_lot=False,
    )
    add_lot(
        api, world, "lot2", product_key="mug", batch_code=batch_code,
        code_date="2026-07-10T00:00:00Z", units_produced=100000,
    )
    add_contact(
        api, world, "ct1", channel="WEB", received_at=CLOCK_EPOCH,
        raw_message="Sharp edge.",
    )
    add_complaint(
        api, world, "cp1", reported_batch_code=reported_code, **SHARP_PACKAGING
    )
    return world


class TestTrendSignalShapeAndWindow:
    def test_each_scope_level_requires_and_forbids_its_own_identifiers(self, api):
        """A missing lot, a forbidden lot and a forbidden line all refuse alike.

        PRD: "On `POST /trend-signals`, `scope_level`, `production_line_id`, and
        `lot_id` are mutually consistent — a `LOT`-scope signal supplies both the
        line and the lot, a `LINE`-scope signal supplies the line and leaves the
        lot empty, and a `PLANT`-scope signal leaves both empty. A violation is
        `ERR_SCOPE_SHAPE_INVALID` (422)."

        Design: Corner/validations/corner_trend_signal_scope_shape_must_match_scope_level
        """
        world = _seed_plant_with_one_sharp_edge_report(
            api, clock="2026-08-01T00:00:00Z", batch_code="MUG-88",
            reported_code="MUG88",
        )
        lead = world.headers("ql1")
        plant_id = world["plant"]["id"]
        line_id = world["line"]["id"]
        window = ("2026-07-20T00:00:00Z", "2026-08-02T00:00:00Z")

        misshapen = (
            trend_signal_payload("LOT", plant_id, *window, production_line_id=line_id),
            trend_signal_payload(
                "LINE", plant_id, *window,
                production_line_id=line_id, lot_id=world["lots"]["lot2"]["id"],
            ),
            trend_signal_payload(
                "PLANT", plant_id, *window, production_line_id=line_id
            ),
        )
        for payload in misshapen:
            refused = api.create_trend_signal(payload, lead)
            validate_error(refused, ApiErrorId.SCOPE_SHAPE_INVALID, 422)

        accepted = validate_success(
            api.create_trend_signal(
                trend_signal_payload("PLANT", plant_id, *window), lead
            ),
            201,
        )
        assert accepted["scope_level"] == "PLANT"
        assert accepted["detection_source"] == "MANUAL"
        assert accepted["membership_count"] == 1

        _rows, meta = validate_paginated(
            api.list_trend_signals(lead, {"plant_id": plant_id})
        )
        assert meta["total_count"] == 1

    def test_a_zero_length_window_fails_before_the_membership_rule_is_reached(self, api):
        """The window guard and the empty-membership guard are separate refusals.

        PRD: "On `POST /trend-signals`, `window_end` is strictly after
        `window_start` — otherwise `ERR_WINDOW_INVALID` (422)." And:
        "`ERR_SIGNAL_EMPTY_MEMBERSHIP` (422) sits alongside the signal rules: it
        is returned when an investigation is opened on a signal whose
        `membership_count` is 0, and when a manually raised window turns out to
        contain no eligible complaint at all."

        Design: Corner/validations/corner_signal_window_end_must_be_strictly_after_window_start
        """
        world = _seed_plant_with_one_sharp_edge_report(
            api, clock="2026-08-05T00:00:00Z", batch_code="MUG-99",
            reported_code="MUG99",
        )
        lead = world.headers("ql1")
        plant_id = world["plant"]["id"]

        zero_length = api.create_trend_signal(
            trend_signal_payload(
                "PLANT", plant_id, "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"
            ),
            lead,
        )
        validate_error(zero_length, ApiErrorId.WINDOW_INVALID, 422)

        inverted = api.create_trend_signal(
            trend_signal_payload(
                "PLANT", plant_id, "2026-08-02T00:00:00Z", "2026-08-01T00:00:00Z"
            ),
            lead,
        )
        validate_error(inverted, ApiErrorId.WINDOW_INVALID, 422)

        valid_but_empty = api.create_trend_signal(
            trend_signal_payload(
                "PLANT", plant_id, "2026-08-03T00:00:00Z", "2026-08-03T00:00:00.001Z"
            ),
            lead,
        )
        validate_error(valid_but_empty, ApiErrorId.SIGNAL_EMPTY_MEMBERSHIP, 422)

        occupied = validate_success(
            api.create_trend_signal(
                trend_signal_payload(
                    "PLANT", plant_id, "2026-08-05T00:00:00Z", "2026-08-05T00:00:00.001Z"
                ),
                lead,
            ),
            201,
        )
        assert occupied["membership_count"] == 1


# ---------------------------------------------------------------------------
# Envelope and conditional guards
# ---------------------------------------------------------------------------
class TestPaginationBounds:
    def test_the_limit_range_is_inclusive_and_anything_outside_it_is_rejected(
        self, api
    ):
        """Zero, 101 and a negative offset are refused; 1, 100 and the defaults hold.

        PRD: "`limit` sets the maximum number of records returned; it defaults to
        10 when omitted, with a minimum accepted value of 1 and a maximum of 100.
        `offset` sets how many records to skip and defaults to 0; the smallest
        accepted value is 0 and there is no upper bound. A `limit` outside 1
        through 100, a non-integer `limit` or `offset`, or a negative `offset` is
        rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/corner_pagination_bounds_are_enforced_at_both_ends
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        agent = world.headers("ag1")

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            refused = api.list_consumers(agent, params)
            validate_error(refused, ApiErrorId.VALIDATION, 400)

        _rows, low_bound = validate_paginated(
            api.list_consumers(agent, {"limit": 1, "offset": 0})
        )
        assert low_bound["limit"] == 1
        assert low_bound["total_count"] == 1

        _rows, high_bound = validate_paginated(api.list_consumers(agent, {"limit": 100}))
        assert high_bound["limit"] == 100
        assert high_bound["has_more"] is False

        _rows, defaults = validate_paginated(api.list_consumers(agent))
        assert defaults["limit"] == 10
        assert defaults["offset"] == 0


class TestConditionalGuards:
    def test_a_kit_cannot_ship_until_the_consumer_has_a_postal_code(self, api):
        """The same dispatch is refused, then accepted once the address is filled in.

        PRD: "On `POST /sample-kits/{id}/ship`, the consumer's `postal_code` is
        present — otherwise `ERR_CONSUMER_ADDRESS_MISSING` (422)."

        Design: Corner/validations/corner_postal_code_is_required_before_a_kit_ships
        """
        world = seed_base_world(
            api,
            actor_keys=("ag1", "sup1"),
            consumer={"postal_code": None, "email": "rin@example.com"},
        )
        assert world["consumer"]["postal_code"] is None
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={
                "channel": "EMAIL",
                "raw_message": "Soft matter, happy to post it back.",
            },
            **SOFT_FOREIGN_MATTER,
        )
        add_kit(
            api, world, world["complaints"]["cp1"]["id"], "k1",
            kit_code="K-950", seal_id_issued="SEAL-950",
        )
        kit_id = world["kits"]["k1"]["id"]
        agent = world.headers("ag1")
        assert world["kits"]["k1"]["status"] == "REQUESTED"

        addressless = api.ship_sample_kit(kit_id, {}, agent)
        validate_error(addressless, ApiErrorId.CONSUMER_ADDRESS_MISSING, 422)
        unshipped = validate_success(api.get_sample_kit(kit_id, agent))
        assert unshipped["status"] == "REQUESTED"
        assert unshipped["shipped_at"] is None

        patched = validate_success(
            api.update_consumer(
                world["consumer"]["id"], {"postal_code": "60601"}, agent
            )
        )
        assert patched["postal_code"] == "60601"

        shipped = validate_success(
            api.ship_sample_kit(kit_id, {"carrier_note": "Prepaid label."}, agent)
        )
        assert shipped["status"] == "SHIPPED"
        assert shipped["shipped_at"] == CLOCK_EPOCH_MS
        assert shipped["expected_return_by"] == "2026-08-15T00:00:00.000Z"

        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], agent)
        )
        assert consumer["open_kit_count"] == 1

    def test_a_template_capped_one_step_milder_cannot_answer_the_complaint(self, api):
        """S3 is milder than S2 and refused; a template capped at S2 is accepted.

        PRD: "On `POST /complaints/{id}/respond`, the template's
        `max_band_allowed` is no less severe than the complaint's
        `effective_severity_band` — otherwise `ERR_TEMPLATE_BAND_TOO_LOW` (422)."

        Design: Corner/validations/corner_template_band_must_be_at_least_as_severe_as_the_complaint
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_template(
            api, world, "t3", template_code="T-ILL-S3", title="Mild illness reply",
            body="Sorry to hear this.", applies_to_type="ILLNESS",
            max_band_allowed="S3",
        )
        add_template(
            api, world, "t2", template_code="T-ILL-S2",
            title="Serious illness reply", body="We are escalating this.",
            applies_to_type="ILLNESS", max_band_allowed="S2",
        )
        seed_triaged_complaint(
            api,
            world,
            complaint_type="ILLNESS",
            medical_attention_sought=True,
            contact_overrides={"raw_message": "Ill, saw a doctor."},
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        assert_severity(
            world["complaints"]["cp1"], adjudicated_score=80.63, effective_band="S2"
        )
        agent = world.headers("ag1")

        too_mild = api.respond_to_complaint(
            complaint_id, respond_payload(world["templates"]["t3"]["id"]), agent
        )
        validate_error(too_mild, ApiErrorId.TEMPLATE_BAND_TOO_LOW, 422)

        answered = validate_success(
            api.respond_to_complaint(
                complaint_id, respond_payload(world["templates"]["t2"]["id"]), agent
            )
        )
        assert answered["handling_status"] == "IN_RESOLUTION"
        assert answered["responded_at"] == CLOCK_EPOCH_MS
        assert answered["responded_template_id"] == world["templates"]["t2"]["id"]

        refused_template = validate_success(
            api.get_response_template(world["templates"]["t3"]["id"], agent)
        )
        assert refused_template["usage_count"] == 0
        used_template = validate_success(
            api.get_response_template(world["templates"]["t2"]["id"], agent)
        )
        assert used_template["usage_count"] == 1


class TestFiscalPreconditionsSatisfied:
    def test_an_approval_passes_when_every_fiscal_clause_is_met(self, api):
        """Tier rank, separate decider, payout under the ceiling, no kit in flight.

        PRD: "On `POST /remedies/{id}/decide`, the deciding staff member's
        `authority_tier` rank is at least the remedy's `authority_tier_required`
        rank, the decider differs from the author, and the computed payout does
        not exceed the goodwill ceiling."

        Design: Corner/validations/corner_all_fiscal_preconditions_satisfied_lets_approval_through
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        seed_triaged_complaint(
            api,
            world,
            complaint_type="QUALITY",
            units_claimed=2,
            contact_overrides={"channel": "EMAIL", "raw_message": "Two stale packs."},
        )
        remedy = add_remedy(
            api, world, world["complaints"]["cp1"]["id"], "rm1",
            remedy_type="REFUND", requested_value_cents=4900,
        )
        assert_goodwill_math(remedy, 4900, 0.10, 490, 5390, "TIER_2")
        assert remedy["kit_returned_credit_applied"] is False

        submitted = submit_remedy(api, world, remedy["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["payout_cents"] == 5390

        approved = validate_success(
            api.decide_remedy(
                remedy["id"],
                {"decision": "APPROVE", "decision_note": "Approved."},
                world.headers("sup1"),
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_ref"] == world.actor("sup1").id
        assert approved["authored_by_ref"] == world.actor("ag1").id

        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(consumer, authorized=5390, outstanding=5390, paid=0, voided=0)
