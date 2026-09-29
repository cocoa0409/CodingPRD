"""Two amendment types share one deadline formula but move different inputs,
and one mitigation waterfall runs under two different round caps."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import (
    assert_deadline,
    assert_field,
    assert_money,
    assert_movement_state,
    assert_petition_offer,
)
from test_helpers.fixtures import (
    LATE_ARRIVAL_ASSESSED,
    LATE_ARRIVAL_CLOCK,
    M1_TRANSIT_DAYS,
    build_departed_movement,
    build_late_arrival_claim,
)

THREE_PORTS = ["ny", "chicago", "la"]


class TestDeadlineAnchorVariants:
    """An approved diversion rebases the transit anchor; an approved extension
    does not."""

    def test_approved_diversion_rebases_the_anchor_to_the_decision_instant(self, client):
        """A diversion decided nineteen days into the transit moves the anchor to
        the decision instant, so the same 35-day window lands on 2026-09-24
        instead of 2026-09-05.

        PRD: "For a **`DIVERSION`**: the movement's `destination_port_id` becomes the identifier of the port whose `port_code` was requested; its `in_bond_type` becomes `requested_in_bond_type` when one was supplied and is left alone otherwise; `deadline_anchor_utc` is rebased to `decided_at`, the decision instant read from the logical clock; and `transit_days_allowed` and `transit_deadline_utc` are recomputed with the interport surcharge re-evaluated against the **new** destination port's `region_code`."

        Design: Difficulty/dual_variant_calc/transit_deadline_anchor_rebases_on_diversion_but_not_on_extension
        """
        world = build_departed_movement(client, port_aliases=THREE_PORTS)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-08-20T00:00:00Z")
        amendment = world.submit_diversion(
            movement_id,
            requested_destination_port_code=factories.PORT_LA_CODE,
            requested_in_bond_type="IT",
        )

        decided = validate_success(
            client.decide_amendment(
                amendment["id"],
                factories.amendment_approval_payload("DIVERSION_GRANTED"),
                world.officer,
            ),
            200,
        )

        assert_field(decided, "status", "APPROVED", "amendment")
        assert_field(
            decided,
            "resulting_deadline_utc",
            "2026-09-24T00:00:00Z",
            "amendment",
        )

        movement = world.read_movement(movement_id)
        assert_deadline(
            movement,
            anchor="2026-08-20T00:00:00Z",
            deadline="2026-09-24T00:00:00Z",
            transit_days_allowed=M1_TRANSIT_DAYS,
            extension_days_granted=0,
        )
        assert_field(movement, "destination_port_id", world.ports["la"], "movement")
        assert_movement_state(movement, transit_status="IN_TRANSIT")

    def test_approved_extension_leaves_the_anchor_at_the_filing_instant(self, client):
        """An extension decided at the same instant grants ten days but leaves the
        anchor on 2026-08-01, so the deadline moves only by the granted days.

        PRD: "On an extension approval `deadline_anchor_utc` is **not** touched; it remains `filed_at`, and only `transit_deadline_utc` moves out."

        Design: Difficulty/dual_variant_calc/transit_deadline_anchor_rebases_on_diversion_but_not_on_extension
        """
        world = build_departed_movement(client, port_aliases=THREE_PORTS)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-08-20T00:00:00Z")
        amendment = world.submit_extension(movement_id, requested_days=10)

        decided = validate_success(
            client.decide_amendment(
                amendment["id"],
                factories.amendment_approval_payload("CONGESTION_VERIFIED", 10),
                world.officer,
            ),
            200,
        )

        assert_field(decided, "status", "APPROVED", "amendment")
        assert_field(decided, "granted_days", 10, "amendment")
        assert_field(
            decided, "resulting_deadline_utc", "2026-09-15T00:00:00Z", "amendment"
        )

        movement = world.read_movement(movement_id)
        assert_deadline(
            movement,
            anchor="2026-08-01T00:00:00Z",
            deadline="2026-09-15T00:00:00Z",
            transit_days_allowed=M1_TRANSIT_DAYS + 10,
            extension_days_granted=10,
        )
        assert_field(movement, "destination_port_id", world.ports["chicago"], "movement")
        assert_movement_state(movement, transit_status="IN_TRANSIT")


class TestMitigationRoundVariants:
    """The same four mitigation factors against the same gross yield different
    offers in round 1 and round 2, because only the cap changes."""

    def test_first_round_offer_is_capped_at_half_the_assessment(self, client):
        """Four factors accumulate 0.85 of raw credit, but a round-one petition
        caps the percentage at 0.50, netting 617.30 plus the flat 100.00 fee.

        PRD: "Step three applies a round-dependent cap: fifty hundredths when the petition's `round` is 1, seventy-five hundredths when it is 2."

        Design: Difficulty/dual_variant_calc/mitigation_offer_diverges_between_first_and_supplemental_round
        """
        world, claim = build_late_arrival_claim(client, LATE_ARRIVAL_CLOCK)
        assert_money(claim["assessed_amount"], LATE_ARRIVAL_ASSESSED, "assessed_amount")

        petition = validate_success(
            client.file_petition(
                factories.petition_payload(
                    claim["id"],
                    claim["version"],
                    factories.FOUR_FACTOR_MITIGATION,
                    "PET-0001",
                ),
                world.carrier,
            ),
            201,
        )

        assert_field(petition, "status", "SUBMITTED", "petition")
        assert_petition_offer(
            petition,
            mitigation_pct=0.50,
            net_before_fee=617.30,
            processing_fee=100.00,
            offer_amount=717.30,
            prior_violation_count=0,
            petition_round=1,
        )

    def test_supplemented_round_recomputes_the_offer_under_the_larger_cap(self, client):
        """Supplementing the identical four factors moves the petition to round 2,
        lifts the cap to 0.75 and produces 408.65 — a strictly smaller offer than
        the 717.30 of round one.

        PRD: "An accepted supplement increases `round` by one, replaces `mitigation_factors` and `narrative_reference` with the supplied values, moves the petition `SUPPLEMENT_REQUESTED → SUBMITTED`, and recomputes `mitigation_pct`, `net_before_fee`, `processing_fee`, and `offer_amount` under the round-2 cap of seventy-five hundredths."

        Design: Difficulty/dual_variant_calc/mitigation_offer_diverges_between_first_and_supplemental_round
        """
        world, claim = build_late_arrival_claim(client, LATE_ARRIVAL_CLOCK)
        first_round = world.file_petition(
            claim["id"],
            factories.FOUR_FACTOR_MITIGATION,
            "PET-0001",
            expected_claim_version=claim["version"],
        )
        assert_money(first_round["offer_amount"], 717.30, "round one offer_amount")
        world.decide_petition(
            first_round["id"], "REQUEST_SUPPLEMENT", "NEED_SEAL_EVIDENCE"
        )

        supplemented = validate_success(
            client.supplement_petition(
                first_round["id"],
                factories.petition_supplement_payload(
                    factories.FOUR_FACTOR_MITIGATION, "PET-0001-S1"
                ),
                world.carrier,
            ),
            200,
        )

        assert_field(supplemented, "round", 2, "petition")
        assert_field(supplemented, "status", "SUBMITTED", "petition")
        assert_petition_offer(
            supplemented,
            mitigation_pct=0.75,
            net_before_fee=308.65,
            processing_fee=100.00,
            offer_amount=408.65,
            prior_violation_count=0,
        )
        assert supplemented["offer_amount"] != first_round["offer_amount"], (
            "the round-two offer must differ from the round-one offer because the "
            "cap changed"
        )

        assert_money(
            world.read_claim(claim["id"])["assessed_amount"],
            LATE_ARRIVAL_ASSESSED,
            "claim assessed_amount",
        )
