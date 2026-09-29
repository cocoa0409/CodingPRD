"""Round trips that must leave the arithmetic exactly where they found it: the
four goodwill accounts and the three lot complaint buckets."""

from test_helpers import (
    add_complaint,
    add_contact,
    assert_goodwill_ledger,
    assert_lot_buckets,
    assert_two_decimal_value,
    seed_approved_remedy,
    seed_base_world,
    seed_triaged_complaint,
    validate_success,
)

# ---------------------------------------------------------------------------
# The four goodwill accounts across approve, fulfil and void
# ---------------------------------------------------------------------------
def _seed_approved_refund_without_a_kit(api):
    """A 5,390-cent refund approved on a quality complaint, no sample involved."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    seed_triaged_complaint(api, world, complaint_type="QUALITY", units_claimed=2)
    seed_approved_remedy(
        api,
        world,
        world["complaints"]["cp1"]["id"],
        "rm1",
        remedy_type="REFUND",
        requested_value_cents=4900,
    )
    return world


def _consumer(api, world):
    return validate_success(
        api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
    )


def _lot(api, world):
    return validate_success(
        api.get_production_lot(world["lot"]["id"], world.headers("sup1"))
    )


class TestGoodwillLedgerConservation:
    def test_approval_parks_the_payout_in_the_outstanding_account(self, api):
        """Authorized and outstanding rise together and nothing is paid yet.

        PRD: "Approval raises the consumer's `goodwill_authorized_cents` and
        `goodwill_outstanding_cents` each by `payout_cents`."

        Design: Difficulty/compensating_invariant/goodwill_ledger_conserves_authorized_across_approve_fulfill_void
        """
        world = _seed_approved_refund_without_a_kit(api)
        remedy = world["remedies"]["rm1"]
        assert remedy["base_value_cents"] == 4900
        assert remedy["uplift_cents"] == 490
        assert remedy["payout_cents"] == 5390

        assert_goodwill_ledger(
            _consumer(api, world), authorized=5390, outstanding=5390, paid=0, voided=0
        )
        assert _lot(api, world)["goodwill_charged_cents"] == 0

    def test_fulfilment_moves_the_money_and_charges_the_lot(self, api):
        """Outstanding empties into paid and the lot picks up the charge.

        PRD: "Fulfilment moves the remedy `APPROVED → FULFILLED`, stamps
        `fulfilled_at`, moves `payout_cents` out of the consumer's
        `goodwill_outstanding_cents` and into `goodwill_paid_cents`, and — when
        the complaint has a resolved lot — raises that lot's
        `goodwill_charged_cents` by `payout_cents`."

        Design: Difficulty/compensating_invariant/goodwill_ledger_conserves_authorized_across_approve_fulfill_void
        """
        world = _seed_approved_refund_without_a_kit(api)

        fulfilled = validate_success(
            api.fulfill_remedy(
                world["remedies"]["rm1"]["id"],
                {"fulfilment_reference": "CHK-7781"},
                world.headers("sup1"),
            )
        )
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["fulfilled_at"] is not None

        assert_goodwill_ledger(
            _consumer(api, world), authorized=5390, outstanding=0, paid=5390, voided=0
        )
        assert _lot(api, world)["goodwill_charged_cents"] == 5390

    def test_void_after_fulfilment_conserves_the_authorized_total(self, api):
        """Paid empties into voided, the lot charge is reversed, authorized never moves.

        PRD: "A `CareSupervisor` may void a remedy, optionally with a `reason`,
        from either `APPROVED` or `FULFILLED`, provided the parent complaint is
        not `CLOSED`; the remedy moves to `VOIDED_AFTER_FULFILLMENT`, which is
        terminal, `payout_cents` moves out of the consumer's
        `goodwill_paid_cents` and into `goodwill_voided_cents`, and the lot's
        `goodwill_charged_cents` is lowered by `payout_cents`."

        Design: Difficulty/compensating_invariant/goodwill_ledger_conserves_authorized_across_approve_fulfill_void
        """
        world = _seed_approved_refund_without_a_kit(api)
        supervisor = world.headers("sup1")
        validate_success(
            api.fulfill_remedy(
                world["remedies"]["rm1"]["id"],
                {"fulfilment_reference": "CHK-7781"},
                supervisor,
            )
        )

        voided = validate_success(
            api.void_remedy(
                world["remedies"]["rm1"]["id"],
                {"reason": "Payment returned undeliverable."},
                supervisor,
            )
        )
        assert voided["status"] == "VOIDED_AFTER_FULFILLMENT"
        assert voided["fulfilled_at"] is not None

        assert_goodwill_ledger(
            _consumer(api, world), authorized=5390, outstanding=0, paid=0, voided=5390
        )
        assert _lot(api, world)["goodwill_charged_cents"] == 0


# ---------------------------------------------------------------------------
# The three lot buckets across a duplicate round trip
# ---------------------------------------------------------------------------
def _seed_two_indistinguishable_complaints(api):
    """The same story told twice by the same consumer against the same lot."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    add_contact(api, world, "ct1", channel="EMAIL")
    for key in ("cpa", "cpb"):
        add_complaint(api, world, key, complaint_type="QUALITY")
    return world


class TestLotBucketConservationAcrossDuplicates:
    def test_two_linked_complaints_start_in_the_provisional_bucket(self, api):
        """Both untriaged complaints count as linked and provisional.

        PRD: "`linked_complaint_count` is the total number of complaints ever
        linked to a lot, and it is split exhaustively across
        `provisional_complaint_count` (linked, not `DUPLICATE`, no adjudicated
        severity yet), `adjudicated_complaint_count` (linked, not `DUPLICATE`,
        carrying an adjudicated severity) and `duplicate_complaint_count`
        (linked and currently in `DUPLICATE`)."

        Design: Difficulty/compensating_invariant/lot_complaint_bucket_counts_conserve_across_duplicate_round_trip
        """
        world = _seed_two_indistinguishable_complaints(api)

        assert_lot_buckets(
            _lot(api, world), linked=2, provisional=2, adjudicated=0, duplicate=0
        )
        assert _consumer(api, world)["complaint_count"] == 2

    def test_marking_a_duplicate_shifts_a_bucket_without_changing_the_total(self, api):
        """One unit crosses from provisional to duplicate and the link total holds.

        PRD: "The lot counters shift one unit into `duplicate_complaint_count`
        from whichever bucket the complaint currently occupies — out of
        `provisional_complaint_count` for an `INTAKE` complaint and out of
        `adjudicated_complaint_count` for a `TRIAGED` one — leaving
        `linked_complaint_count` untouched."

        Design: Difficulty/compensating_invariant/lot_complaint_bucket_counts_conserve_across_duplicate_round_trip
        """
        world = _seed_two_indistinguishable_complaints(api)

        marked = validate_success(
            api.mark_complaint_duplicate(
                world["complaints"]["cpb"]["id"],
                {"duplicate_of_complaint_id": world["complaints"]["cpa"]["id"]},
                world.headers("sup1"),
            )
        )
        assert marked["handling_status"] == "DUPLICATE"
        assert marked["duplicate_of_complaint_id"] == world["complaints"]["cpa"]["id"]

        assert_lot_buckets(
            _lot(api, world), linked=2, provisional=1, adjudicated=0, duplicate=1
        )
        assert _consumer(api, world)["complaint_count"] == 1

    def test_duplicate_is_excluded_from_the_provisional_rate(self, api):
        """The rate halves because only one complaint remains in the numerator.

        PRD: "The `provisional` variant — the default, used when `variant` is
        omitted or set to `provisional` — counts every complaint linked to the lot
        whose `handling_status` is not `DUPLICATE`, triaged or not."

        Design: Difficulty/compensating_invariant/lot_complaint_bucket_counts_conserve_across_duplicate_round_trip
        """
        world = _seed_two_indistinguishable_complaints(api)
        supervisor = world.headers("sup1")

        before = validate_success(
            api.get_lot_complaint_rate(
                world["lot"]["id"], supervisor, {"variant": "provisional"}
            )
        )
        assert before["numerator"] == 2
        assert_two_decimal_value(before["rate_ppm"], 10.00)

        validate_success(
            api.mark_complaint_duplicate(
                world["complaints"]["cpb"]["id"],
                {"duplicate_of_complaint_id": world["complaints"]["cpa"]["id"]},
                supervisor,
            )
        )

        after = validate_success(
            api.get_lot_complaint_rate(
                world["lot"]["id"], supervisor, {"variant": "provisional"}
            )
        )
        assert after["numerator"] == 1
        assert_two_decimal_value(after["rate_ppm"], 5.00)

    def test_unmarking_restores_every_count_it_touched(self, api):
        """The complaint returns to intake and the buckets, rate and count come back.

        PRD: "Either way `duplicate_of_complaint_id` is cleared and the
        consumer's `complaint_count` rises by one."

        Design: Difficulty/compensating_invariant/lot_complaint_bucket_counts_conserve_across_duplicate_round_trip
        """
        world = _seed_two_indistinguishable_complaints(api)
        supervisor = world.headers("sup1")
        validate_success(
            api.mark_complaint_duplicate(
                world["complaints"]["cpb"]["id"],
                {"duplicate_of_complaint_id": world["complaints"]["cpa"]["id"]},
                supervisor,
            )
        )

        restored = validate_success(
            api.unmark_complaint_duplicate(
                world["complaints"]["cpb"]["id"],
                {"reason": "Distinct packs after all."},
                supervisor,
            )
        )
        assert restored["handling_status"] == "INTAKE"
        assert restored["duplicate_of_complaint_id"] is None

        assert_lot_buckets(
            _lot(api, world), linked=2, provisional=2, adjudicated=0, duplicate=0
        )
        assert _consumer(api, world)["complaint_count"] == 2
        rate = validate_success(
            api.get_lot_complaint_rate(
                world["lot"]["id"], supervisor, {"variant": "provisional"}
            )
        )
        assert rate["numerator"] == 2
        assert_two_decimal_value(rate["rate_ppm"], 10.00)
