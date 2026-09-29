"""Dual-variant derivations and pinned-order formulas.

Two variants of the same underlying rule are written into two different stored
fields (preliminary vs final timeliness on one return envelope; estimated vs
actual postage on one mailing batch), and two formulas whose evaluation order is
pinned by the contract (per-packet surcharge rounding, and the propagated cure
deadline).
"""
from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    adjudicate_cure_notice,
    api_client,
    create_ballot_request,
    create_trained_reviewer,
    get_accountability,
    get_cure_notice,
    get_election,
    get_envelope,
    get_success_data,
    issue_cure_notice,
    make_signature_reviewer_headers,
    open_review,
    set_clock,
    setup_election,
    setup_received_envelopes,
    setup_sealed_batch,
    submit_cure_evidence,
    validate_success,
)

CLERK = TEST_USERS["elections_clerk_headers"]


def _instant(value):
    """Parse an emitted ISO 8601 UTC instant, tolerating the fractional digits."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _decide_missing_signature(review):
    """Submit MISSING_SIGNATURE, which carries no similarity_score at all."""
    headers = make_signature_reviewer_headers(review["reviewer_id"])
    return get_success_data(
        api_client.submit_signature_decision(review["id"],
                                             {"decision": "MISSING_SIGNATURE"}, headers))


def _setup_cure_required_pool(count):
    """`count` DROPBOX envelopes received before the return deadline, each carried
    to CURE_REQUIRED by one submitted MISSING_SIGNATURE round-one review."""
    create_trained_reviewer(full_name="Rae Lin", party_affiliation="NPP")
    bundle = setup_received_envelopes(count=count, intake_at="2026-11-03T12:00:00Z",
                                      intake_channel="DROPBOX")
    for envelope in bundle["envelopes"]:
        _decide_missing_signature(open_review(envelope["id"]))
    bundle["envelopes"] = [get_envelope(row["id"]) for row in bundle["envelopes"]]
    return bundle


class TestEnvelopeTimelinessVariants:
    """The preliminary verdict written at intake against the final verdict the
    canvass checkpoint writes onto the identical row."""

    def test_illegible_postmark_inside_grace_window_diverges_between_variants(
            self, admin_headers):
        """An illegible postmark inside the grace window is the one row where the two
        verdicts disagree, and the sweep never rewrites the provisional value.

        "In the final variant, an envelope inside the grace window whose `postmark_legible` is false, or whose `postmark_date` is null, becomes `UNTIMELY` — no presumption survives the canvass."

        Design: Difficulty/dual_variant_calc/envelope_timeliness_preliminary_vs_final_on_illegible_postmark
        """
        bundle = setup_received_envelopes(
            count=1, intake_at="2026-11-05T10:00:00Z", intake_channel="USPS",
            envelope_overrides={"postmark_legible": False})
        envelope = bundle["envelopes"][0]
        assert envelope["preliminary_timeliness"] == "PROVISIONAL_TIMELY_POSTMARK"
        assert envelope["final_timeliness"] is None
        assert envelope["custody_status"] == "SEALED"

        set_clock("2026-11-06T00:00:00Z")
        sweep = validate_success(
            api_client.run_canvass_sweep(bundle["election"]["id"], {}, admin_headers), 200)
        assert sweep["finalized_envelope_count"] == 1
        assert sweep["sequestered_envelope_count"] == 1

        after = get_envelope(envelope["id"])
        assert after["final_timeliness"] == "UNTIMELY"
        assert after["preliminary_timeliness"] == "PROVISIONAL_TIMELY_POSTMARK"
        assert after["custody_status"] == "SEQUESTERED"
        assert after["signature_status"] == "UNVERIFIED"

    def test_legible_postmark_on_election_date_yields_timely_by_postmark(self, admin_headers):
        """A legible postmark dated on the election date is provisional at intake and
        earns the distinct final value reserved for postmark rescue.

        "An envelope with a legible postmark whose `postmark_date` is on or before `election_date` is recorded as `TIMELY_BY_POSTMARK`, a distinct value from the plain `TIMELY` reserved for envelopes that beat the deadline outright."

        Design: Difficulty/dual_variant_calc/envelope_timeliness_preliminary_vs_final_on_illegible_postmark
        """
        bundle = setup_received_envelopes(
            count=1, intake_at="2026-11-05T10:00:00Z", intake_channel="USPS",
            envelope_overrides={"postmark_date": "2026-11-03", "postmark_legible": True})
        envelope = bundle["envelopes"][0]
        assert envelope["preliminary_timeliness"] == "PROVISIONAL_TIMELY_POSTMARK"

        set_clock("2026-11-06T00:00:00Z")
        sweep = validate_success(
            api_client.run_canvass_sweep(bundle["election"]["id"], {}, admin_headers), 200)
        assert sweep["finalized_envelope_count"] == 1
        assert sweep["sequestered_envelope_count"] == 0

        after = get_envelope(envelope["id"])
        assert after["final_timeliness"] == "TIMELY_BY_POSTMARK"
        assert after["preliminary_timeliness"] == "PROVISIONAL_TIMELY_POSTMARK"
        assert after["custody_status"] == "SEALED"

    def test_legible_postmark_after_election_date_is_untimely_in_both_variants(
            self, admin_headers):
        """A postmark dated after the election date is refused by both variants, so the
        two verdicts agree on this row.

        "An envelope with a legible postmark dated strictly after `election_date` is recorded as `UNTIMELY`."

        Design: Difficulty/dual_variant_calc/envelope_timeliness_preliminary_vs_final_on_illegible_postmark
        """
        bundle = setup_received_envelopes(
            count=1, intake_at="2026-11-05T10:00:00Z", intake_channel="USPS",
            envelope_overrides={"postmark_date": "2026-11-04", "postmark_legible": True})
        envelope = bundle["envelopes"][0]
        assert envelope["preliminary_timeliness"] == "UNTIMELY"

        set_clock("2026-11-06T00:00:00Z")
        sweep = validate_success(
            api_client.run_canvass_sweep(bundle["election"]["id"], {}, admin_headers), 200)
        assert sweep["finalized_envelope_count"] == 1
        assert sweep["sequestered_envelope_count"] == 1

        after = get_envelope(envelope["id"])
        assert after["final_timeliness"] == "UNTIMELY"
        assert after["preliminary_timeliness"] == "UNTIMELY"
        assert after["custody_status"] == "SEQUESTERED"

    def test_dropbox_return_gets_no_grace_window_in_either_variant(self, admin_headers):
        """A drop-box return carries no postmark, so neither variant may grant it the
        grace window the postmarked channel enjoys.

        "For the two channels that carry no carrier postmark — `DROPBOX` and `IN_PERSON` — both judgments are identical and there is no grace at all: the verdict is `TIMELY` when `received_at` is at or before `return_deadline_at`, and `UNTIMELY` otherwise."

        Design: Difficulty/dual_variant_calc/envelope_timeliness_preliminary_vs_final_on_illegible_postmark
        """
        bundle = setup_received_envelopes(
            count=1, intake_at="2026-11-05T10:00:00Z", intake_channel="DROPBOX")
        envelope = bundle["envelopes"][0]
        assert envelope["preliminary_timeliness"] == "UNTIMELY"
        assert envelope["postmark_date"] is None

        set_clock("2026-11-06T00:00:00Z")
        validate_success(
            api_client.run_canvass_sweep(bundle["election"]["id"], {}, admin_headers), 200)

        after = get_envelope(envelope["id"])
        assert after["final_timeliness"] == "UNTIMELY"
        assert after["preliminary_timeliness"] == "UNTIMELY"
        assert after["custody_status"] == "SEQUESTERED"


class TestPostageEstimatedVersusActualVariants:
    """The estimated figure frozen at seal against the actual figure recomputed at
    dispatch over the packets that are still queued."""

    @staticmethod
    def _sealed_uocava_pair(uocava_status="MILITARY"):
        """One UOCAVA batch holding two 57 g packets, sealed so its estimate is frozen."""
        election = setup_election(clock="2026-09-10T00:00:00Z")
        return setup_sealed_batch(election, weights=(57, 57), batch_type="UOCAVA",
                                  scheduled_send_date="2026-09-15",
                                  voter_overrides={"uocava_status": uocava_status})

    def test_actual_falls_below_frozen_estimate_when_a_request_is_superseded(self):
        """A request superseded after the seal spoils its packet, so the actual variant
        drops one whole packet below the estimate frozen over the same two packets.

        "Because packets spoiled between seal and dispatch are excluded from the actual variant while the estimated variant already froze them in, the actual figure is strictly below the frozen estimate whenever a request was superseded after sealing, and equal to it otherwise."

        Design: Difficulty/dual_variant_calc/postage_estimated_vs_actual_after_request_supersession
        """
        bundle = self._sealed_uocava_pair()
        election, batch = bundle["election"], bundle["batch"]
        assert bundle["packets"][0]["packet_postage_cents"] == 216
        assert bundle["packets"][1]["packet_postage_cents"] == 216
        estimated = batch["estimated_postage_cents"]
        assert estimated == 432

        voter_two = get_success_data(api_client.get_voter(bundle["voters"][1]["id"], CLERK))
        create_ballot_request(voter_two, election, request_channel="PHONE")

        dispatched = validate_success(api_client.dispatch_batch(batch["id"], CLERK), 200)
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["estimated_postage_cents"] == 432
        assert dispatched["actual_postage_cents"] == 216
        assert estimated - dispatched["actual_postage_cents"] == 216

        spoiled = get_success_data(
            api_client.get_ballot_packet(bundle["packets"][1]["id"], CLERK))
        assert spoiled["status"] == "SPOILED"
        superseded = get_success_data(
            api_client.get_ballot_request(bundle["requests"][1]["id"], CLERK))
        assert superseded["status"] == "SUPERSEDED"

        accountability = get_accountability(election["id"])
        assert accountability["postage_committed_cents"] == 432
        assert accountability["postage_actual_cents"] == 216

    def test_actual_equals_frozen_estimate_when_nothing_is_spoiled(self):
        """With no supersession between seal and dispatch the two variants land on the
        same cents over the same packet set.

        "The **actual** variant of the postage assessment is then computed over the packets whose status is `QUEUED` at dispatch time and written to `actual_postage_cents`, and added to the election's `postage_actual_cents`."

        Design: Difficulty/dual_variant_calc/postage_estimated_vs_actual_after_request_supersession
        """
        bundle = self._sealed_uocava_pair(uocava_status="OVERSEAS")
        election, batch = bundle["election"], bundle["batch"]
        assert batch["estimated_postage_cents"] == 432

        dispatched = validate_success(api_client.dispatch_batch(batch["id"], CLERK), 200)
        assert dispatched["actual_postage_cents"] == 432
        assert dispatched["actual_postage_cents"] == dispatched["estimated_postage_cents"]

        accountability = get_accountability(election["id"])
        assert accountability["postage_committed_cents"] == 432
        assert accountability["postage_actual_cents"] == 432

    def test_seal_moves_only_the_committed_accumulator_and_never_the_actual_one(self):
        """The two variants feed two separate accumulators: sealing commits the estimate
        while the actual figure stays where it was until a dispatch happens.

        "`postage_actual_cents` is untouched by both seal and cancel and remains at its pre-seal value; it accumulates only at dispatch, as the sum of `actual_postage_cents` over dispatched batches."

        Design: Difficulty/dual_variant_calc/postage_estimated_vs_actual_after_request_supersession
        """
        bundle = self._sealed_uocava_pair()
        election, batch = bundle["election"], bundle["batch"]
        assert batch["actual_postage_cents"] is None

        sealed_view = get_accountability(election["id"])
        assert sealed_view["postage_committed_cents"] == 432
        assert sealed_view["postage_actual_cents"] == 0

        validate_success(api_client.dispatch_batch(batch["id"], CLERK), 200)
        after = get_accountability(election["id"])
        assert after["postage_committed_cents"] == 432
        assert after["postage_actual_cents"] == 432


class TestPerPacketSurchargeRoundingOrder:
    """The overseas surcharge is rounded on each packet before the batch is summed,
    which is one cent away from the forbidden sum-then-round order."""

    @staticmethod
    def _sealed_overseas_batch(weights):
        election = setup_election(clock="2026-09-10T00:00:00Z")
        return setup_sealed_batch(election, weights=weights, batch_type="UOCAVA",
                                  scheduled_send_date="2026-09-15",
                                  voter_overrides={"uocava_status": "OVERSEAS"})

    def test_two_fifty_seven_gram_overseas_packets_seal_at_432_not_433(self):
        """Two tier-two overseas packets each pay a surcharge rounded down to 19 cents;
        rounding the pooled 38.7 cents once instead would report 433.

        "The overseas surcharge is rounded to a whole cent **per packet**, and the batch total is then the sum of the already-rounded per-packet figures."

        Design: Difficulty/combinatorial_formula/postage_surcharge_rounding_order_pinned_per_packet
        """
        bundle = self._sealed_overseas_batch((57, 57))
        for packet in bundle["packets"]:
            assert packet["packet_postage_cents"] == 216

        estimated = bundle["batch"]["estimated_postage_cents"]
        assert estimated == 432
        assert estimated != 433

        accountability = get_accountability(bundle["election"]["id"])
        assert accountability["postage_committed_cents"] == 432

    def test_three_fifty_seven_gram_overseas_packets_seal_at_648_not_649(self):
        """The one-cent gap grows with the packet count: three packets pay 57 cents of
        surcharge under the pinned order and 58 under the forbidden one.

        "A batch total computed by summing outbound charges first, taking fifteen percent of that sum, and rounding once is wrong; the two orders differ by as much as one cent per packet."

        Design: Difficulty/combinatorial_formula/postage_surcharge_rounding_order_pinned_per_packet
        """
        bundle = self._sealed_overseas_batch((57, 57, 57))
        for packet in bundle["packets"]:
            assert packet["packet_postage_cents"] == 216

        estimated = bundle["batch"]["estimated_postage_cents"]
        assert estimated == 648
        assert estimated != 649

        accountability = get_accountability(bundle["election"]["id"])
        assert accountability["postage_committed_cents"] == 648

    @pytest.mark.parametrize("grams,uocava_status,expected_cents", [
        (28, "NONE", 141),
        (57, "NONE", 197),
        (85, "NONE", 253),
        (86, "NONE", 309),
        (28, "OVERSEAS", 152),
        (57, "OVERSEAS", 216),
        (100, "OVERSEAS", 345),
    ])
    def test_four_components_sum_per_packet_with_the_surcharge_already_rounded(
            self, grams, uocava_status, expected_cents):
        """Each packet's figure is the four components summed once, with the overweight
        extension and the surcharge rounding both resolved on the single packet.

        "The sum of those four components is the packet's `packet_postage_cents`."

        Design: Difficulty/combinatorial_formula/postage_surcharge_rounding_order_pinned_per_packet
        """
        election = setup_election(clock="2026-09-10T00:00:00Z")
        bundle = setup_sealed_batch(election, weights=(grams,), batch_type="SUPPLEMENTAL",
                                   scheduled_send_date="2026-09-15",
                                   voter_overrides={"uocava_status": uocava_status})
        assert bundle["packets"][0]["packet_postage_cents"] == expected_cents
        assert bundle["batch"]["estimated_postage_cents"] == expected_cents


class TestPropagatedCureDeadlineOrder:
    """The cure deadline is clamped by the canvass lock while the canvass length is
    itself driven by the open-cure count, resolved by one pinned evaluation order."""

    def test_third_notice_extends_the_canvass_and_takes_the_later_deadline(self):
        """Counting the new notice inclusively crosses the extension threshold, so the
        third notice both lengthens the canvass and receives the later clamp.

        "Step five: `cure_deadline_at` on the notice is the earlier of that cure base deadline and the canvass lock instant reduced by one whole day."

        Design: Difficulty/combinatorial_formula/cure_deadline_circular_canvass_length_propagation
        """
        bundle = _setup_cure_required_pool(3)
        election = bundle["election"]
        assert _instant(election["canvass_lock_at"]) == _instant("2026-11-20T20:00:00Z")
        set_clock("2026-11-04T00:00:00Z")

        first = validate_success(
            api_client.create_cure_notice(bundle["envelopes"][0]["id"], CLERK), 201)
        assert first["open_cure_count_at_issue"] == 1
        assert first["canvass_days_at_issue"] == 17
        assert _instant(first["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")

        second = validate_success(
            api_client.create_cure_notice(bundle["envelopes"][1]["id"], CLERK), 201)
        assert second["open_cure_count_at_issue"] == 2
        assert second["canvass_days_at_issue"] == 17
        assert _instant(second["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")

        third = validate_success(
            api_client.create_cure_notice(bundle["envelopes"][2]["id"], CLERK), 201)
        assert third["open_cure_count_at_issue"] == 3
        assert third["canvass_days_at_issue"] == 21
        assert _instant(third["cure_deadline_at"]) == _instant("2026-11-23T20:00:00Z")

        refreshed = get_election(election["id"])
        assert refreshed["canvass_days"] == 21
        assert _instant(refreshed["canvass_lock_at"]) == _instant("2026-11-24T20:00:00Z")
        assert refreshed["open_cure_count"] == 3

    def test_earlier_notice_keeps_its_frozen_deadline_after_the_extension(self):
        """The first notice's three frozen values survive untouched once a later notice
        pushes the election onto the extended canvass length.

        "A later notice that pushes the open-cure count past the threshold does **not** extend an earlier notice's deadline."

        Design: Difficulty/combinatorial_formula/cure_deadline_circular_canvass_length_propagation
        """
        bundle = _setup_cure_required_pool(3)
        set_clock("2026-11-04T00:00:00Z")
        first = issue_cure_notice(bundle["envelopes"][0]["id"])
        issue_cure_notice(bundle["envelopes"][1]["id"])

        before = get_cure_notice(first["id"])
        assert _instant(before["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")
        assert before["canvass_days_at_issue"] == 17

        third = validate_success(
            api_client.create_cure_notice(bundle["envelopes"][2]["id"], CLERK), 201)
        assert third["canvass_days_at_issue"] == 21

        after = get_cure_notice(first["id"])
        assert _instant(after["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")
        assert after["canvass_days_at_issue"] == 17
        assert after["open_cure_count_at_issue"] == 1

    def test_two_open_cures_stay_on_the_standard_canvass_length(self):
        """Two open notices sit below the extension threshold, so the election keeps the
        standard canvass length and the standard lock instant.

        "Step two: the election's `canvass_days` becomes the extended canvass length of 21 whole days when that open-cure count is at least 3, and otherwise remains the standard 17 whole days."

        Design: Difficulty/combinatorial_formula/cure_deadline_circular_canvass_length_propagation
        """
        bundle = _setup_cure_required_pool(2)
        set_clock("2026-11-04T00:00:00Z")
        first = issue_cure_notice(bundle["envelopes"][0]["id"])
        second = issue_cure_notice(bundle["envelopes"][1]["id"])

        assert _instant(first["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")
        assert _instant(second["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")
        assert second["canvass_days_at_issue"] == 17

        refreshed = get_election(bundle["election"]["id"])
        assert refreshed["canvass_days"] == 17
        assert _instant(refreshed["canvass_lock_at"]) == _instant("2026-11-20T20:00:00Z")
        assert refreshed["open_cure_count"] == 2

    def test_extended_canvass_length_never_returns_to_standard_once_reached(self):
        """Closing every cure empties the open-cure count without shortening the canvass
        the third notice had already extended.

        "The election's own `canvass_days` and `canvass_lock_at`, by contrast, are monotone: once the extended 21-day length has been reached they never return to the standard 17, even if every cure subsequently closes."

        Design: Difficulty/combinatorial_formula/cure_deadline_circular_canvass_length_propagation
        """
        bundle = _setup_cure_required_pool(3)
        set_clock("2026-11-04T00:00:00Z")
        notices = [issue_cure_notice(envelope["id"]) for envelope in bundle["envelopes"]]

        extended = get_election(bundle["election"]["id"])
        assert extended["canvass_days"] == 21
        assert _instant(extended["canvass_lock_at"]) == _instant("2026-11-24T20:00:00Z")

        for notice in notices:
            submit_cure_evidence(notice["id"], affirmation_signed=True)
            adjudicate_cure_notice(notice["id"], "CURE")

        after = get_election(bundle["election"]["id"])
        assert after["open_cure_count"] == 0
        assert after["canvass_days"] == 21
        assert _instant(after["canvass_lock_at"]) == _instant("2026-11-24T20:00:00Z")
