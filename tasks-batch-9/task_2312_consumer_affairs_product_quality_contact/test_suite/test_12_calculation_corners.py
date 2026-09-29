"""The arithmetic at its awkward edges: a custody projection that never repairs,
transit measured to the inclusive hour, batch codes matched exactly after an
aggressive normalisation, sentiment read from two vantage points, goodwill priced
in bands that are not monotonic, and a filing that lands on the deadline itself."""

from test_helpers import (
    ApiErrorId,
    add_complaint,
    add_consumer,
    add_contact,
    add_line,
    add_lot,
    add_remedy,
    append_custody,
    assert_goodwill_ledger,
    assert_goodwill_math,
    assert_severity,
    assert_two_decimal_value,
    complaint_payload,
    determine_report,
    find_report,
    lab_accept_kit,
    receive_kit,
    seed_base_world,
    seed_shipped_kit,
    seed_triaged_complaint,
    set_clock,
    submit_report,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

SOFT_FOREIGN_MATTER = dict(complaint_type="FOREIGN_MATERIAL", foreign_object_class="SOFT")


# ---------------------------------------------------------------------------
# The custody chain integrity projection
# ---------------------------------------------------------------------------
class TestCustodyChainProjection:
    def test_a_wrong_seal_at_the_second_step_breaks_the_chain_for_good(self, api):
        """The mismatch is recorded, the chain breaks at once and never recovers.

        PRD: "The chain is `INTACT` only when all six of the following hold: every
        appended position carries the event type the required sequence expects
        there; all five required events are present; `occurred_at` is
        non-decreasing across the ordered chain; the `CONSUMER_SEALED` event's
        `seal_id_observed` equals the kit's `seal_id_issued`; the `LAB_RECEIVED`
        event's `seal_id_observed` also equals `seal_id_issued`; and
        `transit_hours` is at most 240 — a transit of exactly 240.00 hours is
        still `INTACT`." And: "Acceptance sets `disposition` to `USABLE` when
        `chain_integrity_status` is `INTACT` and forces it to `UNUSABLE`
        otherwise, moves the parent complaint `AWAITING_SAMPLE → IN_RESOLUTION`,
        and lowers the consumer's `open_kit_count` by one."

        Design: Corner/calculations/corner_custody_projection_breaks_on_seal_mismatch_and_never_repairs
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"raw_message": "Soft foreign matter."},
            **SOFT_FOREIGN_MATTER,
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        seed_shipped_kit(
            api, world, complaint_id, "k1",
            kit_code="K-701", seal_id_issued="SEAL-701",
        )
        kit_id = world["kits"]["k1"]["id"]

        mismatched = append_custody(
            api, world, kit_id, "CONSUMER_SEALED", "2026-08-01T12:00:00Z",
            actor_label="Rin Sato", seal_id_observed="SEAL-799",
        )
        assert mismatched["sequence_no"] == 2
        assert mismatched["seal_id_observed"] == "SEAL-799"
        two_events_in = validate_success(
            api.get_sample_kit(kit_id, world.headers("ql1"))
        )
        assert two_events_in["chain_integrity_status"] == "BROKEN"
        assert two_events_in["custody_event_count"] == 2

        append_custody(
            api, world, kit_id, "CARRIER_PICKUP", "2026-08-02T00:00:00Z",
            actor_label="Courier 88",
        )
        set_clock(api, "2026-08-06T00:00:00Z")
        append_custody(
            api, world, kit_id, "LAB_RECEIVED", "2026-08-06T00:00:00Z",
            actor="ql1", actor_label="Lab intake", seal_id_observed="SEAL-701",
        )
        received = receive_kit(api, world, kit_id)
        assert_two_decimal_value(received["transit_hours"], 96.00)
        assert received["chain_integrity_status"] == "BROKEN"

        append_custody(
            api, world, kit_id, "LAB_OPENED", "2026-08-06T02:00:00Z",
            actor="ql1", actor_label="Analyst 3",
        )
        accepted = lab_accept_kit(api, world, kit_id)
        assert accepted["custody_event_count"] == 5
        assert accepted["chain_integrity_status"] == "BROKEN"
        assert accepted["disposition"] == "UNUSABLE"

        complaint = validate_success(
            api.get_complaint(complaint_id, world.headers("sup1"))
        )
        assert complaint["handling_status"] == "IN_RESOLUTION"

    def test_exactly_two_hundred_forty_transit_hours_is_still_intact(self, api):
        """Half an hour more on an otherwise identical chain flips it to broken.

        PRD: "`transit_hours` is the number of hours between the `CARRIER_PICKUP`
        event's `occurred_at` and the `LAB_RECEIVED` event's `occurred_at`,
        rounded half up to 2 decimal places."

        Design: Corner/calculations/corner_transit_hours_boundary_at_exactly_max_transit_hours
        """
        world = _seed_two_kits_awaiting_the_lab(api)

        on_the_bound, kit_a = _finish_the_chain(
            api, world, "ka", "SEAL-801", "2026-08-12T00:00:00Z"
        )
        assert_two_decimal_value(on_the_bound["transit_hours"], 240.00)
        assert kit_a["chain_integrity_status"] == "INTACT"

        past_the_bound, kit_b = _finish_the_chain(
            api, world, "kb", "SEAL-802", "2026-08-12T00:30:00Z"
        )
        assert_two_decimal_value(past_the_bound["transit_hours"], 240.50)
        assert kit_b["chain_integrity_status"] == "BROKEN"

        assert kit_a["custody_event_count"] == kit_b["custody_event_count"] == 5
        for key in ("cpa", "cpb"):
            assert_severity(
                world["complaints"][key],
                adjudicated_score=48.38,
                adjudicated_band="S3",
                effective_band="S3",
            )
        _rows, meta = validate_paginated(
            api.list_regulatory_reports(world.headers("ro1"))
        )
        assert meta["total_count"] == 0
        lot = validate_success(
            api.get_production_lot(world["lot"]["id"], world.headers("ql1"))
        )
        assert lot["release_status"] == "RELEASED"


def _seed_two_kits_awaiting_the_lab(api):
    """Two consumers, one soft-matter complaint each, both kits picked up."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1", "ro1"))
    add_consumer(
        api, world, "c2", external_ref="C-2", full_name="Ola Berg",
        postal_code="60602",
    )
    for suffix, consumer_key, channel, kit_code, seal in (
        ("a", "c1", "PHONE", "K-801", "SEAL-801"),
        ("b", "c2", "EMAIL", "K-802", "SEAL-802"),
    ):
        add_contact(
            api, world, f"ct{suffix}", consumer_key=consumer_key, channel=channel,
            raw_message=f"Soft matter {suffix.upper()}.",
        )
        add_complaint(
            api, world, f"cp{suffix}", contact_key=f"ct{suffix}", **SOFT_FOREIGN_MATTER
        )
        world["complaints"][f"cp{suffix}"] = triage(
            api, world, world["complaints"][f"cp{suffix}"]["id"]
        )
        seed_shipped_kit(
            api, world, world["complaints"][f"cp{suffix}"]["id"], f"k{suffix}",
            kit_code=kit_code, seal_id_issued=seal,
        )
        kit_id = world["kits"][f"k{suffix}"]["id"]
        append_custody(
            api, world, kit_id, "CONSUMER_SEALED", "2026-08-01T12:00:00Z",
            actor_label="Sample custodian", seal_id_observed=seal,
        )
        append_custody(
            api, world, kit_id, "CARRIER_PICKUP", "2026-08-02T00:00:00Z",
            actor_label="Courier 88",
        )
    set_clock(api, "2026-08-12T01:00:00Z")
    return world


def _finish_the_chain(api, world, kit_key, seal, lab_received_at):
    """Log the inbound kit, then open it, and read the settled projection."""
    kit_id = world["kits"][kit_key]["id"]
    append_custody(
        api, world, kit_id, "LAB_RECEIVED", lab_received_at,
        actor="ql1", actor_label="Lab intake", seal_id_observed=seal,
    )
    received = receive_kit(api, world, kit_id)
    append_custody(
        api, world, kit_id, "LAB_OPENED", "2026-08-12T01:00:00Z",
        actor="ql1", actor_label="Analyst 3",
    )
    settled = validate_success(api.get_sample_kit(kit_id, world.headers("ql1")))
    return received, settled


# ---------------------------------------------------------------------------
# Batch-code resolution
# ---------------------------------------------------------------------------
class TestBatchCodeResolution:
    def test_normalisation_is_aggressive_but_the_match_is_exact(self, api):
        """Punctuation and case are discarded; one character too few never matches.

        PRD: "The reported code is normalized the same way lot codes are —
        upper-cased with every character that is not a letter A through Z or a
        digit 0 through 9 removed — and compared for exact equality against every
        lot's `normalized_batch_code`. No prefix matching and no fuzzy matching is
        performed."

        Design: Corner/calculations/corner_batch_code_normalization_then_exact_match
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        lot = add_lot(api, world, "lot1", batch_code="a1b-2026/0710")
        assert lot["normalized_batch_code"] == "A1B20260710"
        add_contact(
            api, world, "ct1", channel="WEB",
            raw_message="Three ways of typing the code.",
        )

        spaced = add_complaint(
            api, world, "cp1", reported_batch_code="  a1b 2026/0710 "
        )
        assert spaced["product_identification_status"] == "RESOLVED"
        assert spaced["lot_id"] == lot["id"]
        assert spaced["product_id"] == world["product"]["id"]

        hashed = add_complaint(api, world, "cp2", reported_batch_code="A1B#2026#0710")
        assert hashed["product_identification_status"] == "RESOLVED"
        assert hashed["lot_id"] == lot["id"]

        too_short = add_complaint(api, world, "cp3", reported_batch_code="A1B2026071")
        assert too_short["product_identification_status"] == "UNRESOLVED"
        assert too_short["lot_id"] is None

        too_long = add_complaint(api, world, "cp4", reported_batch_code="A1B20260710X")
        assert too_long["product_identification_status"] == "UNRESOLVED"
        assert too_long["lot_id"] is None

        settled = validate_success(
            api.get_production_lot(lot["id"], world.headers("ag1"))
        )
        assert settled["linked_complaint_count"] == 2
        assert settled["provisional_complaint_count"] == 2

    def test_a_pack_date_that_narrows_to_nothing_is_still_ambiguous(self, api):
        """Two candidates need a pack date, and the wrong pack date is no better.

        PRD: "If more than one lot matches, the `pack_code_date` becomes the
        tie-breaker: the candidates are narrowed to those whose `code_date` equals
        the supplied `pack_code_date`, and only if that narrowing leaves exactly
        one lot does resolution succeed from it. When `pack_code_date` was not
        supplied, or when narrowing still leaves more than one or none, the
        request is refused with `ERR_BATCH_CODE_AMBIGUOUS`."

        Design: Corner/calculations/corner_ambiguous_batch_code_needs_pack_code_date_to_narrow
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        add_line(api, world, "l2", line_code="L-02", nominal_units_per_hour=9000)
        add_lot(
            api, world, "lota", batch_code="SHARED-77",
            code_date="2026-07-01T00:00:00Z", units_produced=100000,
        )
        lotb = add_lot(
            api, world, "lotb", line_key="l2", batch_code="SHARED-77",
            code_date="2026-07-02T00:00:00Z", units_produced=100000,
        )
        add_contact(api, world, "ct1", raw_message="Code SHARED 77.")
        contact_id = world["contacts"]["ct1"]["id"]
        agent = world.headers("ag1")

        without_a_date = api.create_complaint(
            complaint_payload(contact_id, reported_batch_code="shared 77"), agent
        )
        validate_error(without_a_date, ApiErrorId.BATCH_CODE_AMBIGUOUS, 422)

        narrowed_to_nothing = api.create_complaint(
            complaint_payload(
                contact_id,
                reported_batch_code="shared 77",
                pack_code_date="2026-07-05T00:00:00Z",
            ),
            agent,
        )
        validate_error(narrowed_to_nothing, ApiErrorId.BATCH_CODE_AMBIGUOUS, 422)

        narrowed_to_one = validate_success(
            api.create_complaint(
                complaint_payload(
                    contact_id,
                    reported_batch_code="shared 77",
                    pack_code_date="2026-07-02T00:00:00Z",
                ),
                agent,
            ),
            201,
        )
        assert narrowed_to_one["product_identification_status"] == "RESOLVED"
        assert narrowed_to_one["lot_id"] == lotb["id"]

        _rows, meta = validate_paginated(
            api.list_complaints(agent, {"lot_id": lotb["id"]})
        )
        assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The consumer sentiment index
# ---------------------------------------------------------------------------
def _sentiment(api, world, consumer_key="c1", **params):
    consumer_id = world["consumers"][consumer_key]["id"]
    return validate_success(
        api.get_consumer_sentiment(consumer_id, world.headers("sup1"), params or None)
    )


class TestConsumerSentiment:
    def test_a_complaint_exactly_ninety_days_old_already_decays(self, api):
        """One day of age separates a halved penalty from a full one.

        PRD: "Under the default agent view — used when a consumer record is read,
        and when the sentiment read omits `view` or sets it to `agent_view` — a
        complaint whose age has reached 90 days contributes half of its raw
        penalty, with the boundary inclusive so that a complaint exactly 90 days
        old already decays; younger complaints contribute their full penalty."

        Design: Corner/calculations/corner_sentiment_decay_boundary_is_inclusive_at_ninety_days
        """
        world = seed_base_world(
            api,
            clock="2026-05-04T00:00:00Z",
            actor_keys=("ag1", "sup1"),
            lot={"batch_code": "A1B-2026-0410", "code_date": "2026-04-10T00:00:00Z"},
        )
        add_consumer(
            api, world, "c2", external_ref="C-2", full_name="Ola Berg",
            postal_code="60602",
        )
        add_contact(
            api, world, "cta", received_at="2026-05-04T00:00:00Z",
            raw_message="Stale, ninety days ago.",
        )
        add_complaint(
            api, world, "cpa", contact_key="cta", reported_batch_code="A1B20260410"
        )
        older = triage(api, world, world["complaints"]["cpa"]["id"])

        set_clock(api, "2026-05-05T00:00:00Z")
        add_contact(
            api, world, "ctb", consumer_key="c2", received_at="2026-05-05T00:00:00Z",
            raw_message="Stale, eighty-nine days ago.",
        )
        add_complaint(
            api, world, "cpb", contact_key="ctb", reported_batch_code="A1B20260410"
        )
        younger = triage(api, world, world["complaints"]["cpb"]["id"])
        for complaint in (older, younger):
            assert_severity(
                complaint, adjudicated_score=10.75, adjudicated_band="S4",
                effective_band="S4",
            )

        set_clock(api, "2026-08-02T00:00:00Z")

        decayed = _sentiment(api, world, "c1")
        assert_two_decimal_value(decayed["penalty_total"], 1.50)
        assert_two_decimal_value(decayed["sentiment_index"], 48.50)

        undecayed = _sentiment(api, world, "c2")
        assert_two_decimal_value(undecayed["penalty_total"], 3.00)
        assert_two_decimal_value(undecayed["sentiment_index"], 47.00)

        for view in (decayed, undecayed):
            assert_two_decimal_value(view["credit_total"], 0.00)
            assert view["complaint_count_in_window"] == 1

    def test_the_lookback_window_and_the_lifetime_count_disagree_by_one(self, api):
        """A complaint 181 days old leaves the window; the entity still counts it.

        PRD: "Every complaint of that consumer that is not in `DUPLICATE` and
        whose `created_at` is no earlier than 180 days before the logical clock
        counts as in-window and contributes a penalty: 20 points for an
        `effective_severity_band` of `S1`, 12 for `S2`, 6 for `S3`, and 3 for
        `S4`, plus a surcharge of 5 further points whenever the complaint still
        has no `adjudicated_severity_score`."

        Design: Corner/calculations/corner_sentiment_lookback_window_excludes_older_complaints
        """
        world = seed_base_world(
            api,
            clock="2026-02-01T00:00:00Z",
            actor_keys=("ag1", "sup1"),
            lot={"batch_code": "A1B-2026-0110", "code_date": "2026-01-10T00:00:00Z"},
        )
        add_contact(
            api, world, "cta", channel="EMAIL", received_at="2026-02-01T00:00:00Z",
            raw_message="First, just outside the window.",
        )
        add_complaint(
            api, world, "cpa", contact_key="cta", reported_batch_code="A1B20260110"
        )
        triage(api, world, world["complaints"]["cpa"]["id"])

        set_clock(api, "2026-02-02T00:00:00Z")
        add_contact(
            api, world, "ctb", channel="EMAIL", received_at="2026-02-02T00:00:00Z",
            raw_message="Second, exactly on the window edge.",
        )
        add_complaint(
            api, world, "cpb", contact_key="ctb", reported_batch_code="A1B20260110"
        )
        triage(api, world, world["complaints"]["cpb"]["id"])

        set_clock(api, "2026-08-01T00:00:00Z")

        windowed = _sentiment(api, world, "c1")
        assert windowed["complaint_count_in_window"] == 1
        assert_two_decimal_value(windowed["penalty_total"], 1.50)
        assert_two_decimal_value(windowed["sentiment_index"], 48.50)

        entity = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("ag1"))
        )
        assert entity["complaint_count"] == 2
        assert_two_decimal_value(entity["sentiment_index"], 48.50)

    def test_the_two_views_differ_only_by_the_decayed_half(self, api):
        """The aged penalty halves for the agent and stays whole for the executive.

        PRD: "Under `executive_view`, no decay applies and every in-window penalty
        counts at full weight."

        Design: Corner/calculations/corner_sentiment_views_diverge_only_on_decayed_penalties
        """
        world = seed_base_world(
            api,
            clock="2026-04-01T00:00:00Z",
            actor_keys=("ag1", "sup1"),
            lot={"batch_code": "A1B-2026-0310", "code_date": "2026-03-10T00:00:00Z"},
        )
        add_contact(
            api, world, "cta", received_at="2026-04-01T00:00:00Z",
            raw_message="Felt ill, saw a doctor.",
        )
        add_complaint(
            api, world, "cpa", contact_key="cta", complaint_type="ILLNESS",
            reported_batch_code="A1B20260310", medical_attention_sought=True,
        )
        aged = triage(api, world, world["complaints"]["cpa"]["id"])
        assert_severity(
            aged, provisional_score=75.00, adjudicated_score=80.63,
            adjudicated_band="S2", effective_band="S2",
        )
        assert aged["regulatory_status"] == "ESCALATED"

        set_clock(api, "2026-08-01T00:00:00Z")
        add_contact(
            api, world, "ctb", channel="WEB", received_at="2026-08-01T00:00:00Z",
            raw_message="Crackers were stale.",
        )
        add_complaint(
            api, world, "cpb", contact_key="ctb", reported_batch_code="A1B20260310"
        )
        fresh = triage(api, world, world["complaints"]["cpb"]["id"])
        assert_severity(fresh, adjudicated_score=10.75, adjudicated_band="S4")

        agent_view = _sentiment(api, world, "c1", view="agent_view")
        assert agent_view["view"] == "agent_view"
        assert_two_decimal_value(agent_view["penalty_total"], 9.00)
        assert_two_decimal_value(agent_view["sentiment_index"], 41.00)

        executive_view = _sentiment(api, world, "c1", view="executive_view")
        assert executive_view["view"] == "executive_view"
        assert_two_decimal_value(executive_view["penalty_total"], 15.00)
        assert_two_decimal_value(executive_view["sentiment_index"], 35.00)

        assert (
            float(executive_view["penalty_total"]) - float(agent_view["penalty_total"])
        ) == 6.00
        assert executive_view["complaint_count_in_window"] == 2

        entity = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("ag1"))
        )
        assert_two_decimal_value(entity["sentiment_index"], 41.00)


# ---------------------------------------------------------------------------
# Goodwill authorization
# ---------------------------------------------------------------------------
def _seed_triaged_quality_complaint(api, **complaint_overrides):
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    seed_triaged_complaint(
        api,
        world,
        complaint_type="QUALITY",
        contact_overrides={"channel": "EMAIL", "raw_message": "Stale pack."},
        **complaint_overrides,
    )
    return world


class TestGoodwillArithmetic:
    def test_a_replacement_prices_itself_and_ignores_the_request(self, api):
        """Three units at retail plus handling, whatever the consumer asked for.

        PRD: "For a `REPLACEMENT`, `requested_value_cents` is ignored entirely:
        the base is the product's `unit_retail_price_cents` multiplied by
        `units_claimed` or by 3, whichever is smaller, multiplied again by a
        handling factor of 1.15, and rounded half up to a whole number of cents."

        Design: Corner/calculations/corner_replacement_base_uses_unit_cap_and_handling_multiplier
        """
        world = seed_base_world(
            api,
            actor_keys=("ag1", "sup1"),
            product="mug",
            lot={"batch_code": "MUG-77", "units_produced": 100000},
        )
        seed_triaged_complaint(
            api,
            world,
            complaint_type="PACKAGING",
            reported_batch_code="MUG77",
            units_claimed=5,
            contact_overrides={
                "channel": "WEB",
                "raw_message": "Five mugs arrived with crushed sleeves.",
            },
        )

        remedy = add_remedy(
            api, world, world["complaints"]["cp1"]["id"], "rm1",
            remedy_type="REPLACEMENT", requested_value_cents=99,
        )

        assert_goodwill_math(remedy, 6210, 0.05, 311, 6521, "TIER_2")
        assert remedy["kit_returned_credit_applied"] is False
        assert remedy["status"] == "DRAFT"

    def test_one_cent_of_request_moves_the_tier_but_not_the_uplift(self, api):
        """A payout of exactly 2,500 is still tier one; 2,501 is not.

        PRD: "Fourth, `authority_tier_required` is banded from the final payout:
        `TIER_1` when `payout_cents` is at most 2,500, `TIER_2` when it is at most
        7,500, and `TIER_3` above that."

        Design: Corner/calculations/corner_authority_tier_boundary_at_exactly_tier_1_max_payout
        """
        world = _seed_triaged_quality_complaint(api)
        complaint_id = world["complaints"]["cp1"]["id"]

        on_the_bound = add_remedy(
            api, world, complaint_id, "rm1",
            remedy_type="COUPON", requested_value_cents=2273,
        )
        assert_goodwill_math(on_the_bound, 2273, 0.10, 227, 2500, "TIER_1")

        one_cent_more = add_remedy(
            api, world, complaint_id, "rm2",
            remedy_type="COUPON", requested_value_cents=2274,
        )
        assert_goodwill_math(one_cent_more, 2274, 0.10, 227, 2501, "TIER_2")
        assert one_cent_more["uplift_cents"] == on_the_bound["uplift_cents"]

        retired = validate_success(
            api.get_remedy(on_the_bound["id"], world.headers("ag1"))
        )
        assert retired["status"] == "SUPERSEDED"

        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(consumer, authorized=0, outstanding=0, paid=0, voided=0)

    def test_asking_for_one_cent_more_can_pay_out_less(self, api):
        """The higher uplift band carries the smaller rate, and nothing smooths it.

        PRD: "The band is deliberately non-monotonic in the request, because the
        higher band carries the smaller rate: a base of 4,999 cents pays out 5,499
        while a base of 5,000 cents pays out only 5,250."

        Design: Corner/calculations/corner_goodwill_payout_is_non_monotonic_across_the_uplift_bands
        """
        world = _seed_triaged_quality_complaint(api)
        complaint_id = world["complaints"]["cp1"]["id"]

        below = add_remedy(
            api, world, complaint_id, "rm1",
            remedy_type="COUPON", requested_value_cents=4999,
        )
        assert_goodwill_math(below, 4999, 0.10, 500, 5499, "TIER_2")

        at_the_band = add_remedy(
            api, world, complaint_id, "rm2",
            remedy_type="COUPON", requested_value_cents=5000,
        )
        assert_goodwill_math(at_the_band, 5000, 0.05, 250, 5250, "TIER_2")

        assert at_the_band["payout_cents"] < below["payout_cents"]

    def test_the_refund_cap_is_applied_before_the_band_is_chosen(self, api):
        """Over-asking caps the base onto the boundary and lowers the payout.

        PRD: "For a `REFUND`, the base is `requested_value_cents` or the resolved
        lot's product `unit_retail_price_cents` multiplied by the complaint's
        `units_claimed`, whichever is smaller; and if the complaint's kit has
        reached `LAB_ACCEPTED`, a sample-return credit of 799 cents is then added
        to that capped figure and `kit_returned_credit_applied` is set true."

        Design: Corner/calculations/corner_refund_base_is_capped_at_retail_price_times_units_claimed
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_consumer(
            api, world, "c2", external_ref="C-2", full_name="Ola Berg",
            postal_code="60602",
        )
        for suffix, consumer_key, message in (
            ("a", "c1", "Two stale packs, refund please."),
            ("b", "c2", "Two stale packs, refund the lot."),
        ):
            add_contact(
                api, world, f"ct{suffix}", consumer_key=consumer_key, channel="EMAIL",
                raw_message=message,
            )
            add_complaint(
                api, world, f"cp{suffix}", contact_key=f"ct{suffix}",
                complaint_type="QUALITY", units_claimed=2,
            )
            world["complaints"][f"cp{suffix}"] = triage(
                api, world, world["complaints"][f"cp{suffix}"]["id"]
            )

        modest = add_remedy(
            api, world, world["complaints"]["cpa"]["id"], "rma",
            remedy_type="REFUND", requested_value_cents=4900,
        )
        assert_goodwill_math(modest, 4900, 0.10, 490, 5390, "TIER_2")

        greedy = add_remedy(
            api, world, world["complaints"]["cpb"]["id"], "rmb",
            remedy_type="REFUND", requested_value_cents=99000,
        )
        assert_goodwill_math(greedy, 5000, 0.05, 250, 5250, "TIER_2")

        assert greedy["payout_cents"] == modest["payout_cents"] - 140
        assert modest["kit_returned_credit_applied"] is False
        assert greedy["kit_returned_credit_applied"] is False


# ---------------------------------------------------------------------------
# The regulatory filing deadline
# ---------------------------------------------------------------------------
class TestRegulatoryDeadline:
    def test_filing_on_the_deadline_is_on_time_and_one_millisecond_later_is_not(
        self, api
    ):
        """Two reports share a deadline and are filed a millisecond apart.

        PRD: "Filing moves the report `DETERMINED_REPORTABLE → SUBMITTED`, which
        is terminal, stamps `submitted_by_ref` and `submitted_at` from the logical
        clock, advances the complaint `REPORTABLE → SUBMITTED`, and computes
        `submitted_late` as true when `submitted_at` is **strictly after**
        `due_at`."

        Design: Corner/calculations/corner_regulatory_submission_at_exactly_due_at_is_on_time
        """
        world = seed_base_world(
            api,
            actor_keys=("ag1", "sup1", "ro1", "ro2"),
            create_lot=False,
        )
        for key, batch_code, code_date in (
            ("lota", "LOT-DUE-A", "2026-07-10T00:00:00Z"),
            ("lotb", "LOT-DUE-B", "2026-07-11T00:00:00Z"),
        ):
            add_lot(api, world, key, batch_code=batch_code, code_date=code_date)
        for suffix, batch_code, message in (
            ("a", "LOTDUEA", "Ill after eating, saw a doctor. Lot A."),
            ("b", "LOTDUEB", "Ill after eating, saw a doctor. Lot B."),
        ):
            add_contact(api, world, f"ct{suffix}", raw_message=message)
            add_complaint(
                api, world, f"cp{suffix}", contact_key=f"ct{suffix}",
                complaint_type="ILLNESS", reported_batch_code=batch_code,
                foreign_object_class="SOFT", medical_attention_sought=True,
                symptom_codes=["NAUSEA", "CRAMPS"],
            )
            world["complaints"][f"cp{suffix}"] = triage(
                api, world, world["complaints"][f"cp{suffix}"]["id"]
            )
            assert_severity(
                world["complaints"][f"cp{suffix}"],
                adjudicated_score=93.53,
                adjudicated_band="S1",
                effective_band="S1",
            )

        report_a = find_report(api, world, world["complaints"]["cpa"]["id"])
        report_b = find_report(api, world, world["complaints"]["cpb"]["id"])
        assert report_a["due_at"] == "2026-08-02T00:00:00.000Z"
        assert report_b["due_at"] == report_a["due_at"]
        assert report_a.get("submitted_late") is None
        for report in (report_a, report_b):
            determine_report(api, world, report["id"], "REPORTABLE")

        set_clock(api, "2026-08-02T00:00:00Z")
        on_time = submit_report(
            api, world, report_a["id"], agency_reference="AG-77001"
        )
        assert on_time["status"] == "SUBMITTED"
        assert on_time["submitted_at"] == "2026-08-02T00:00:00.000Z"
        assert on_time["submitted_late"] is False

        set_clock(api, "2026-08-02T00:00:00.001Z")
        late = submit_report(api, world, report_b["id"], agency_reference="AG-77002")
        assert late["status"] == "SUBMITTED"
        assert late["submitted_at"] == "2026-08-02T00:00:00.001Z"
        assert late["submitted_late"] is True

        _rows, meta = validate_paginated(
            api.list_regulatory_reports(world.headers("ro1"), {"submitted_late": "true"})
        )
        assert meta["total_count"] == 1

        for suffix in ("a", "b"):
            complaint = validate_success(
                api.get_complaint(
                    world["complaints"][f"cp{suffix}"]["id"], world.headers("sup1")
                )
            )
            assert complaint["regulatory_status"] == "SUBMITTED"
