"""Compensating writes that put back exactly what an earlier write took: a
correction reversal against a recovery bucket, and a late renewal against the
lapse that released a designation slot.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import OFFICER_2_HEADERS, OFFICER_HEADERS, REVIEWER_HEADERS
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X

LOT_CEILING = 2000
SHIPPED = (600, 500, 400)
SHIPPED_TOTAL = 1500
VERIFIED = (400, 200, 100)
VERIFIED_TOTAL = 700
REVERSED_UNITS = 100


def _three_lots_partly_recovered(api):
    """Three shipments of 600, 500 and 400, with 400, 200 and 100 units verified.

    The plan is accepted by OFF-1 so OFF-2 may open the withdrawal round.
    """
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Windrow Fill Services",
            "owner_operator_name": "Windrow Inc",
            "facility_type": "PROCESSOR",
            "state_or_province": "IA",
        },
        person_overrides={"legal_name": "Windrow Brands LLC"},
        listing_overrides={
            "product_name": "Windrow Suntan Lotion",
            "category_code": "12A",
            "lot_authorized_units": LOT_CEILING,
        },
    )
    agent = bundle["agent"]
    records = X.create_distribution_records(
        api, bundle["listing_id"], agent,
        [
            {"lot_code": "LOT-W1", "consignee_name": "Prairie Wholesale",
             "consignee_class": "WHOLESALE", "ship_date": "2026-08-04",
             "delivery_date": "2026-08-08", "units_shipped": SHIPPED[0]},
            {"lot_code": "LOT-W2", "consignee_name": "Cornbelt Retail",
             "consignee_class": "RETAIL", "ship_date": "2026-08-04",
             "delivery_date": "2026-08-08", "units_shipped": SHIPPED[1]},
            {"lot_code": "LOT-W3", "consignee_name": "River City Pharmacy",
             "consignee_class": "CONSUMER", "ship_date": "2026-08-04",
             "delivery_date": "2026-08-08", "units_shipped": SHIPPED[2]},
        ],
    )
    recall = X.recall_with_accepted_plan(
        api, bundle["listing_id"], agent,
        initiation_basis=K.INITIATION_BASIS_VOLUNTARY, officer=OFFICER_HEADERS,
    )
    withdrawal = X.open_withdrawal(api, recall, OFFICER_2_HEADERS, K.DEPTH_RETAIL)
    X.produce_records(api, withdrawal["id"], [r["id"] for r in records], agent)
    X.post_recovery(api, withdrawal["id"], records[0]["id"], VERIFIED[0], agent,
                    K.ENTRY_KIND_VERIFIED_RETURN)
    X.post_recovery(api, withdrawal["id"], records[1]["id"], VERIFIED[1], agent,
                    K.ENTRY_KIND_VERIFIED_RETURN)
    X.post_recovery(api, withdrawal["id"], records[2]["id"], VERIFIED[2], agent,
                    K.ENTRY_KIND_VERIFIED_DESTRUCTION)
    bundle["records"] = records
    bundle["withdrawal_id"] = withdrawal["id"]
    return bundle


def _reverse_a_hundred_verified_returns(api, bundle):
    return get_success_data(
        api.post_recovery_entry(
            bundle["withdrawal_id"],
            F.reversal_entry_payload(
                bundle["records"][0]["id"], REVERSED_UNITS, K.BUCKET_VERIFIED_RETURNED
            ),
            bundle["agent"],
        )
    )


class TestCorrectionReversalConservesShippedUnits:
    """Three invariants survive a compensating reversal of verified units."""

    def test_the_recoveries_leave_every_record_and_the_round_in_balance(self, api):
        """Before any correction, each record's verified and outstanding units add back up to
        what it shipped, and the round's own totals agree with the sum across its records.

        PRD: "Three invariants hold after every entry and every reversal. Per record, `units_verified_returned` plus `units_verified_destroyed` plus `units_outstanding` always equals `units_shipped` exactly — no entry may leave a record out of balance. Per withdrawal, the sum over its linked records of verified-plus-outstanding units always equals `shipped_units_total`, and `outstanding_units_total` always equals the sum of the records' `units_outstanding`."

        Design: Difficulty/compensating_invariant/correction_reversal_preserves_shipped_unit_conservation_and_ledger_sum
        """
        bundle = _three_lots_partly_recovered(api)

        for index, record in enumerate(bundle["records"]):
            stored = X.read_record(api, record["id"])
            A.assert_record_unit_balance(stored)
            assert stored["units_shipped"] == SHIPPED[index]
            assert stored["units_outstanding"] == SHIPPED[index] - VERIFIED[index]

        first = X.read_record(api, bundle["records"][0]["id"])
        assert first["units_verified_returned"] == VERIFIED[0]
        assert first["units_outstanding"] == SHIPPED[0] - VERIFIED[0]

        withdrawal = X.read_withdrawal(api, bundle["withdrawal_id"])
        assert withdrawal["shipped_units_total"] == SHIPPED_TOTAL
        assert withdrawal["verified_recovered_units"] == VERIFIED_TOTAL
        assert withdrawal["outstanding_units_total"] == SHIPPED_TOTAL - VERIFIED_TOTAL

    def test_the_reversal_walks_the_bucket_down_and_the_outstanding_count_back_up(self, api):
        """Reversing 100 verified returns subtracts them from that bucket alone and hands the
        same 100 back to the outstanding count, so the record stays in balance at 600.

        PRD: "The sixth, `CORRECTION_REVERSAL`, names a target bucket and **subtracts** its units from it; the units reversed must not exceed that bucket's current balance, or the entry is refused with `ERR_REVERSAL_EXCEEDS_RECORDED` (HTTP 422), so no bucket is ever driven below zero."
        PRD: "Only the two verified buckets reduce `units_outstanding`, which is at all times `units_shipped` minus the sum of `units_verified_returned` and `units_verified_destroyed`: consignee assertions and in-transit claims are recorded but do not discharge the obligation, because units are only accounted for once someone has actually seen them come back or be destroyed."

        Design: Difficulty/compensating_invariant/correction_reversal_preserves_shipped_unit_conservation_and_ledger_sum
        """
        bundle = _three_lots_partly_recovered(api)

        corrected = _reverse_a_hundred_verified_returns(api, bundle)

        assert corrected["units_verified_returned"] == VERIFIED[0] - REVERSED_UNITS
        assert corrected["units_verified_destroyed"] == 0
        assert corrected["units_outstanding"] == SHIPPED[0] - VERIFIED[0] + REVERSED_UNITS
        assert corrected["units_shipped"] == SHIPPED[0]
        A.assert_record_unit_balance(corrected)

    def test_the_shipped_totals_of_the_round_and_the_product_never_move(self, api):
        """Recovery activity redistributes units between buckets and never changes what was
        shipped: the round's shipped total and the product's distributed total both stand at
        1500 while the verified and outstanding figures trade 100 units between them.

        PRD: "Every entry also refreshes the withdrawal's `reported_recovered_units`, `verified_recovered_units` and `outstanding_units_total`, and the listing's `distributed_units_total`."
        PRD: "That total counts every record of the listing, whatever its recovery state and whether or not it is linked to a withdrawal."

        Design: Difficulty/compensating_invariant/correction_reversal_preserves_shipped_unit_conservation_and_ledger_sum
        """
        bundle = _three_lots_partly_recovered(api)

        _reverse_a_hundred_verified_returns(api, bundle)

        withdrawal = X.read_withdrawal(api, bundle["withdrawal_id"])
        assert withdrawal["shipped_units_total"] == SHIPPED_TOTAL
        assert withdrawal["verified_recovered_units"] == VERIFIED_TOTAL - REVERSED_UNITS
        assert withdrawal["outstanding_units_total"] == (
            SHIPPED_TOTAL - VERIFIED_TOTAL + REVERSED_UNITS
        )
        assert (
            withdrawal["verified_recovered_units"] + withdrawal["outstanding_units_total"]
        ) == SHIPPED_TOTAL

        assert X.read_listing(api, bundle["listing_id"])["distributed_units_total"] == (
            SHIPPED_TOTAL
        )

    def test_the_ledger_deltas_still_sum_to_the_verified_total(self, api):
        """Three verified movements and one reversal write four unit-movement entries in
        append order, the reversal's delta being the removed units negated, and their sum
        reproduces the round's verified total.

        PRD: "And in the ledger, every verified movement appends a `UNIT_MOVEMENT` entry whose `signed_units_delta` is the units added, while every `CORRECTION_REVERSAL` of a verified bucket appends one whose `signed_units_delta` is the units removed, negated — so summing `signed_units_delta` over a record's `UNIT_MOVEMENT` entries always reproduces the record's verified total."

        Design: Difficulty/compensating_invariant/correction_reversal_preserves_shipped_unit_conservation_and_ledger_sum
        """
        bundle = _three_lots_partly_recovered(api)

        _reverse_a_hundred_verified_returns(api, bundle)

        movements = X.ledger_entries(api, bundle["facility_id"], K.ENTRY_TYPE_UNIT_MOVEMENT)
        assert [entry["signed_units_delta"] for entry in movements] == [
            VERIFIED[0], VERIFIED[1], VERIFIED[2], -REVERSED_UNITS
        ]
        A.assert_unit_movement_delta(movements[-1], -REVERSED_UNITS)
        assert sum(entry["signed_units_delta"] for entry in movements) == (
            X.read_withdrawal(api, bundle["withdrawal_id"])["verified_recovered_units"]
        )

    def test_a_reversal_larger_than_the_bucket_balance_is_refused_outright(self, api):
        """The bucket now holds 300, so reversing 400 would drive it negative; the entry is
        refused, the record is left exactly as the first correction left it, and no fifth
        unit-movement entry is written.

        PRD: "The capacity and conservation checks, last of all, in this order: `ERR_DESIGNATION_CAP_EXCEEDED`, `ERR_LOT_CAPACITY_EXCEEDED`, `ERR_RECOVERY_EXCEEDS_OUTSTANDING`, `ERR_REVERSAL_EXCEEDS_RECORDED`."

        Design: Difficulty/compensating_invariant/correction_reversal_preserves_shipped_unit_conservation_and_ledger_sum
        """
        bundle = _three_lots_partly_recovered(api)
        corrected = _reverse_a_hundred_verified_returns(api, bundle)

        validate_error(
            api.post_recovery_entry(
                bundle["withdrawal_id"],
                F.reversal_entry_payload(
                    bundle["records"][0]["id"], VERIFIED[0], K.BUCKET_VERIFIED_RETURNED
                ),
                bundle["agent"],
            ),
            E.ERR_REVERSAL_EXCEEDS_RECORDED,
        )

        after = X.read_record(api, bundle["records"][0]["id"])
        assert after["units_verified_returned"] == corrected["units_verified_returned"]
        assert after["units_outstanding"] == corrected["units_outstanding"]
        A.assert_record_unit_balance(after)

        movements = X.ledger_entries(api, bundle["facility_id"], K.ENTRY_TYPE_UNIT_MOVEMENT)
        assert len(movements) == 4


LAPSE_INSTANT = "2028-08-01T00:00:00Z"


def _lapsed_then_renewed_late(api):
    """A marketed product whose establishment lapses on 2028-08-01 and is then
    renewed inside its grace window on the very same day."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Havenbrook Cosmetics",
            "owner_operator_name": "Havenbrook Ltd",
            "facility_type": "BOTH",
            "state_or_province": "MD",
        },
        person_overrides={"legal_name": "Havenbrook Brands LLC"},
        listing_overrides={
            "product_name": "Havenbrook Eyeliner",
            "category_code": "03B",
        },
    )
    dossier = X.dossier_at_decision(
        api, bundle["listing_id"], bundle["agent"], X.PASSING_EVIDENCE, K.REVIEW_MODE_FULL
    )
    get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
    get_success_data(
        api.decide_listing(
            bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
        )
    )
    bundle["dossier_id"] = dossier["id"]
    X.lapse_facility_via_sweep(api, LAPSE_INSTANT)
    return bundle


def _file_the_late_renewal(api, bundle):
    return get_success_data(
        api.file_renewal(
            bundle["facility_id"],
            F.renewal_payload(K.RENEWAL_KIND_STANDARD),
            bundle["registrant"],
        )
    )


class TestLateRenewalRestoresTheReleasedDesignationSlot:
    """The grace-window renewal puts back the slot, the listing and the count."""

    def test_the_lapse_has_released_the_slot_before_the_renewal_is_filed(self, api):
        """The starting position is the lapse cascade's end state: the establishment frozen,
        the product suspended for the lapse, the designee back to nothing and dormant.

        PRD: "Hop 2, caused by hop 1, walks every product listing of the establishment whose `listing_status` is `SUBMITTED` or `LISTED`, in ascending listing `created_at` order, and moves each to `SUSPENDED` with `suspension_reason` set to `FACILITY_LAPSED`."
        PRD: "Hop 4, caused by hop 3, flips any designee whose `active_designation_count` has reached 0 to `status` `DORMANT`."

        Design: Difficulty/compensating_invariant/late_renewal_restores_the_designation_slot_count_it_released
        """
        bundle = _lapsed_then_renewed_late(api)

        facility = X.read_facility(api, bundle["facility_id"])
        assert facility["registration_status"] == K.REGISTRATION_STATUS_LAPSED
        assert facility["compliance_posture"] == K.POSTURE_FROZEN
        assert facility["listed_product_count"] == 0

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_SUSPENDED
        assert listing["suspension_reason"] == K.SUSPENSION_REASON_FACILITY_LAPSED

        designee = X.read_responsible_person(api, bundle["person_id"])
        assert designee["active_designation_count"] == 0
        assert designee["status"] == K.RP_STATUS_DORMANT

    def test_the_successor_period_is_a_late_renewal_that_leaves_no_gap(self, api):
        """Filed on 2028-08-01, a day after coverage ended, the successor is marked a late
        renewal — yet it still starts the day after the predecessor ended, so the biennial
        cadence has not drifted by the lapse.

        PRD: "The successor's `period_start` is always the predecessor's `period_end` plus one day — the cadence is gap-free and never drifts, even when the filing itself arrives late — and its `period_end`, `renewal_window_open_date` and `grace_end_date` follow the same two-year derivation described above."
        PRD: "The successor's `period_kind` is `RENEWAL` when the logical clock's calendar date is on or before the predecessor's `period_end`, and `LATE_RENEWAL` when that date is after the predecessor's `period_end`."

        Design: Difficulty/compensating_invariant/late_renewal_restores_the_designation_slot_count_it_released
        """
        bundle = _lapsed_then_renewed_late(api)

        successor = _file_the_late_renewal(api, bundle)

        assert successor["period_kind"] == K.PERIOD_KIND_LATE_RENEWAL
        assert successor["sequence_index"] == 2
        assert successor["status"] == K.PERIOD_STATUS_ACTIVE
        A.assert_period_bounds(
            successor, "2028-08-01", "2030-07-31", "2030-05-02", "2030-09-29"
        )
        A.assert_facility_period_mirror(
            X.read_facility(api, bundle["facility_id"]),
            "2028-08-01", "2030-07-31", "2030-05-02", "2030-09-29",
        )

    def test_the_renewal_puts_back_exactly_the_quantities_the_lapse_released(self, api):
        """One listing returns to the register with its suspension reason cleared, the
        designee's count returns to one and with it the active status, and the establishment
        counts its product again — no more and no less than the lapse took away.

        PRD: "The compensation then runs in three hops: hop 1 returns every listing of the establishment whose `listing_status` is `SUSPENDED` **and** whose `suspension_reason` is `FACILITY_LAPSED` to `LISTED` with `suspension_reason` cleared to null; hop 2 re-increments each restored listing's designee `active_designation_count`; hop 3 flips any designee that was `DORMANT` back to `status` `ACTIVE`."

        Design: Difficulty/compensating_invariant/late_renewal_restores_the_designation_slot_count_it_released
        """
        bundle = _lapsed_then_renewed_late(api)

        _file_the_late_renewal(api, bundle)

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED
        assert listing["suspension_reason"] is None

        designee = X.read_responsible_person(api, bundle["person_id"])
        assert designee["active_designation_count"] == 1
        assert designee["status"] == K.RP_STATUS_ACTIVE

        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 1

    def test_the_establishment_is_registered_again_on_its_second_cycle(self, api):
        """The renewal moves the establishment out of the lapse, counts a second registration
        cycle and lifts the posture out of frozen, because no points and no escalation are
        holding it there.

        PRD: "An establishment that has lapsed is not lost: a renewal filed while the logical clock's calendar date is still on or before `grace_end_date` moves it `LAPSED → REGISTERED`, mints the successor period with `period_kind` `LATE_RENEWAL` and a gap-free `period_start`, and recomputes `compliance_posture` — which lifts out of `FROZEN` unless accumulated points or an outstanding escalation still hold it there."

        Design: Difficulty/compensating_invariant/late_renewal_restores_the_designation_slot_count_it_released
        """
        bundle = _lapsed_then_renewed_late(api)

        _file_the_late_renewal(api, bundle)

        facility = X.read_facility(api, bundle["facility_id"])
        assert facility["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
        assert facility["registration_cycle_count"] == 2
        assert facility["compliance_posture"] == K.POSTURE_OPEN
        A.assert_two_decimal_value(facility["serious_event_points"], 0.00, "serious_event_points")

        periods, _meta = validate_paginated(
            api.list_registration_periods(
                bundle["facility_id"], REVIEWER_HEADERS, {"limit": K.MAX_LIMIT}
            )
        )
        assert [period["sequence_index"] for period in periods] == [1, 2]
        assert periods[0]["status"] == K.PERIOD_STATUS_EXPIRED
        assert periods[0]["period_kind"] == K.PERIOD_KIND_INITIAL

    def test_the_safety_dimension_is_deliberately_not_restored(self, api):
        """The lapse also invalidated the cleared dossier, and that is the one thing the
        renewal does not undo: the dossier and the product still demand revalidation, so the
        restored listing is on the register without being marketable.

        PRD: "A posture recomputation that *lowers* the posture never reverses this cascade: once a dossier has been pushed to `REVALIDATION_REQUIRED`, only a fresh submission and a fresh review decision can clear it again."

        Design: Difficulty/compensating_invariant/late_renewal_restores_the_designation_slot_count_it_released
        """
        bundle = _lapsed_then_renewed_late(api)

        _file_the_late_renewal(api, bundle)

        assert X.read_substantiation(api, bundle["dossier_id"])["status"] == (
            K.SUBSTANTIATION_STATUS_REVALIDATION_REQUIRED
        )
        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_REVALIDATION_REQUIRED
        assert listing["marketable"] is False
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED

    def test_the_ledger_takes_the_de_escalation_then_one_entry_per_restored_listing(self, api):
        """The compensating cascade writes the posture move out of frozen and then exactly one
        transition entry for the single listing it restored.

        PRD: "`listed_product_count` and each restored listing's `marketable` flag are recomputed, and the ledger receives a `POSTURE_CHANGE` entry followed by one `STATE_TRANSITION` entry per restored listing in ascending listing `created_at` order."

        Design: Difficulty/compensating_invariant/late_renewal_restores_the_designation_slot_count_it_released
        """
        bundle = _lapsed_then_renewed_late(api)
        before = len(X.ledger_entries(api, bundle["facility_id"]))

        _file_the_late_renewal(api, bundle)

        entries = X.ledger_entries(api, bundle["facility_id"])
        A.assert_ledger_sequence_numbers(entries)
        appended = entries[before:]
        posture_entries = A.find_entries(appended, K.ENTRY_TYPE_POSTURE_CHANGE)
        assert len(posture_entries) == 1
        A.assert_posture_change_entry(posture_entries[0], K.POSTURE_FROZEN, K.POSTURE_OPEN)

        position = appended.index(posture_entries[0])
        following = appended[position + 1]
        assert following["entry_type"] == K.ENTRY_TYPE_STATE_TRANSITION
        assert following["subject_entity"] == "ProductListing"
        assert following["subject_id"] == bundle["listing_id"]
