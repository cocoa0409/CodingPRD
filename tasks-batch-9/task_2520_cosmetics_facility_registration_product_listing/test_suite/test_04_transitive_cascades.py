"""Cascades that propagate through four hops: one late adverse-event report, and
one registration lapse observed by the sweep.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import REVIEWER_HEADERS
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X

EVENT_RECEIVED_AT = "2026-08-05T10:00:00Z"
LATE_FILING_INSTANT = "2026-09-01T12:00:00Z"


def _listed_product_with_cleared_dossier(api, listing_overrides):
    """A marketable listing whose dossier is sitting in ADEQUATE."""
    bundle = X.registered_facility_with_listing(api, listing_overrides=listing_overrides)
    dossier = X.dossier_at_decision(api, bundle["listing_id"], bundle["agent"])
    assert dossier["status"] == K.SUBSTANTIATION_STATUS_ADEQUATE
    get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
    listed = get_success_data(
        api.decide_listing(
            bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
        )
    )
    assert listed["marketable"] is True
    bundle["listing"] = listed
    bundle["dossier"] = dossier
    return bundle


def _late_report_cascade(api):
    """One serious event received 2026-08-05 and reported twelve days past its deadline."""
    bundle = _listed_product_with_cleared_dossier(
        api,
        listing_overrides={
            "product_name": "Harbour Lane Baby Shampoo",
            "category_code": "01A",
            "product_form": K.PRODUCT_FORM_RINSE_OFF,
        },
    )
    X.set_clock(api, "2026-08-06T00:00:00Z")
    event = X.record_serious_event(
        api, bundle["listing_id"], bundle["agent"], EVENT_RECEIVED_AT
    )
    assert event["report_status"] == K.EVENT_STATUS_REPORT_DUE
    X.set_clock(api, LATE_FILING_INSTANT)
    filed = X.file_report(api, event["id"], bundle["agent"])
    return bundle, filed


class TestLateSeriousReportCascade:
    """Points, then posture, then every cleared dossier, then every listing."""

    def test_the_late_base_and_the_capped_lateness_factor_land_on_the_event(self, api):
        """Filed 2026-09-01 against a 2026-08-20 deadline, the report overran by twelve
        whole days and scores the late base times the capped factor, and the establishment's
        open reporting obligation is discharged.

        PRD: "After it the event takes `REPORT_DUE → REPORTED_LATE` with `lateness_days` set to the number of whole days by which the filing overran, computed as the elapsed time from `deadline_at` to `submitted_at` divided by one day and rounded **up** to the next integer."
        PRD: "Independently of the cascade, both `open_serious_event_count` values fall by 1, because the event is no longer awaiting a report."

        Design: Difficulty/transitive_cascade/late_serious_report_cascades_points_posture_dossier_and_listing
        """
        bundle, filed = _late_report_cascade(api)

        assert filed["report_status"] == K.EVENT_STATUS_REPORTED_LATE
        assert filed["lateness_days"] == 12
        assert filed["submitted_at"] == LATE_FILING_INSTANT
        A.assert_deadline_at_end_of_day(filed["deadline_at"], "2026-08-20")
        A.assert_two_decimal_value(filed["event_points"], 10.00, "event_points")

        assert X.read_facility(api, bundle["facility_id"])["open_serious_event_count"] == 0
        assert X.read_listing(api, bundle["listing_id"])["open_serious_event_count"] == 0

    def test_hop_two_escalates_the_posture_and_bars_the_abbreviated_renewal_path(self, api):
        """10.00 points is exactly the restricted threshold, and a restricted establishment
        can no longer take the abbreviated renewal path.

        PRD: "Hop 2 recomputes the establishment's `serious_event_points` and `compliance_posture`."
        PRD: "A change of ownership mid-period is therefore enough to force the establishment down the `STANDARD` path for the remainder of that period, and so is any posture escalation, since a `RESTRICTED` or `FROZEN` establishment is never abbreviated-eligible."

        Design: Difficulty/transitive_cascade/late_serious_report_cascades_points_posture_dossier_and_listing
        """
        bundle, _filed = _late_report_cascade(api)

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 10.00, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_RESTRICTED
        assert facility["abbreviated_renewal_eligible"] is False

    def test_hops_three_and_four_invalidate_the_dossier_and_the_listing(self, api):
        """The escalation reaches the cleared dossier and, through it, the listing: both
        demand revalidation and the product stops being marketable while staying on the
        register.

        PRD: "Hop 3 fires only when hop 2 escalated the posture out of `OPEN`: every `ADEQUATE` substantiation dossier under any listing of the establishment moves to `REVALIDATION_REQUIRED`, visited in ascending order of the listing's `created_at` and then the dossier's `created_at`."
        PRD: "Hop 4 follows each of those: the listing's `safety_status` becomes `REVALIDATION_REQUIRED` and its `marketable` flag becomes false."

        Design: Difficulty/transitive_cascade/late_serious_report_cascades_points_posture_dossier_and_listing
        """
        bundle, _filed = _late_report_cascade(api)

        dossier = X.read_substantiation(api, bundle["dossier"]["id"])
        assert dossier["status"] == K.SUBSTANTIATION_STATUS_REVALIDATION_REQUIRED

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_REVALIDATION_REQUIRED
        assert listing["marketable"] is False
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 1

    def test_the_ledger_records_the_cascade_in_its_fixed_order(self, api):
        """The three entries the cascade appends arrive report first, then the posture move
        carrying both values, then one transition for the revalidated listing.

        PRD: "The ledger records this in a fixed order: one `ADVERSE_EVENT_REPORT` entry against the event, then — only when the posture actually changed — one `POSTURE_CHANGE` entry carrying the before and after values, then one `STATE_TRANSITION` entry per revalidated listing."

        Design: Difficulty/transitive_cascade/late_serious_report_cascades_points_posture_dossier_and_listing
        """
        bundle, filed = _late_report_cascade(api)

        entries = X.ledger_entries(api, bundle["facility_id"])
        A.assert_ledger_sequence_numbers(entries)
        for entry in entries:
            A.assert_ledger_entry_shape(entry)

        tail = entries[-3:]
        A.assert_entry_types_in_order(tail, [
            K.ENTRY_TYPE_ADVERSE_EVENT_REPORT,
            K.ENTRY_TYPE_POSTURE_CHANGE,
            K.ENTRY_TYPE_STATE_TRANSITION,
        ])
        assert tail[0]["subject_entity"] == "AdverseEvent"
        assert tail[0]["subject_id"] == filed["id"]
        A.assert_non_posture_entry_nulls(tail[0])
        A.assert_posture_change_entry(tail[1], K.POSTURE_OPEN, K.POSTURE_RESTRICTED)
        assert tail[2]["subject_entity"] == "ProductListing"
        assert tail[2]["subject_id"] == bundle["listing_id"]


def _periods_of(api, facility_id):
    rows, _ = validate_paginated(
        api.list_registration_periods(facility_id, REVIEWER_HEADERS, {"limit": K.MAX_LIMIT})
    )
    return rows


def _lapsed_by_sweep(api):
    """A marketable listing whose establishment runs out of coverage on 2028-08-01."""
    bundle = _listed_product_with_cleared_dossier(
        api,
        listing_overrides={
            "product_name": "Atelier Nail Extension Base",
            "category_code": "08D",
        },
    )
    counters = X.lapse_facility_via_sweep(api)
    return bundle, counters


class TestSweepLapseCascade:
    """Posture, listing, designation slot and dormancy all move on one sweep."""

    def test_the_lapse_freezes_the_establishment_and_expires_its_period(self, api):
        """Past the coverage window the sweep lapses the registration, the lapsed clause
        forces the posture to frozen even with no points at all, and the active period is
        retired.

        PRD: "An establishment whose `registration_status` is `REGISTERED` or `RENEWAL_DUE` and whose `current_period_end` has passed is moved to `LAPSED` and counted in `lapsed_facility_count`, firing the four-hop lapse cascade of §3.1 in full: the `compliance_posture` is recomputed and forced to `FROZEN` by the lapsed clause, every listing of the establishment whose `listing_status` is `SUBMITTED` or `LISTED` is suspended with `suspension_reason` `FACILITY_LAPSED` and counted in `suspended_listing_count`, each suspended listing's designee has its `active_designation_count` decremented and flips to `DORMANT` at zero, and the establishment's `ACTIVE` registration period is moved to `EXPIRED`."

        Design: Difficulty/transitive_cascade/sweep_lapse_cascades_posture_listing_designation_and_dormancy
        """
        bundle, counters = _lapsed_by_sweep(api)

        assert counters["lapsed_facility_count"] == 1
        assert counters["suspended_listing_count"] == 1

        facility = X.read_facility(api, bundle["facility_id"])
        assert facility["registration_status"] == K.REGISTRATION_STATUS_LAPSED
        assert facility["compliance_posture"] == K.POSTURE_FROZEN
        A.assert_two_decimal_value(facility["serious_event_points"], 0.00, "serious_event_points")
        assert facility["listed_product_count"] == 0

        periods = _periods_of(api, bundle["facility_id"])
        assert len(periods) == 1
        assert periods[0]["sequence_index"] == 1
        assert periods[0]["period_kind"] == K.PERIOD_KIND_INITIAL
        assert periods[0]["status"] == K.PERIOD_STATUS_EXPIRED

    def test_the_suspension_releases_the_designation_slot_and_returns_the_designee_to_dormant(
        self, api
    ):
        """Hop 2 suspends the listed product for the lapse, hop 3 hands the designation slot
        back, and hop 4 flips the designee dormant once its count reaches zero.

        PRD: "Hop 3, caused by hop 2, decrements the `active_designation_count` of each suspended listing's designee by 1."
        PRD: "It is derived: a responsible person is `ACTIVE` whenever `active_designation_count` is 1 or more, and `DORMANT` when it is exactly 0."

        Design: Difficulty/transitive_cascade/sweep_lapse_cascades_posture_listing_designation_and_dormancy
        """
        bundle, _counters = _lapsed_by_sweep(api)

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_SUSPENDED
        assert listing["suspension_reason"] == K.SUSPENSION_REASON_FACILITY_LAPSED
        assert listing["marketable"] is False

        designee = X.read_responsible_person(api, bundle["person_id"])
        assert designee["active_designation_count"] == 0
        assert designee["status"] == K.RP_STATUS_DORMANT

    def test_the_freeze_is_an_escalation_so_the_cleared_dossier_needs_revalidating(self, api):
        """Forcing the posture to frozen is an escalation out of open, so the same sweep call
        moves the establishment's cleared dossier and its listing to revalidation.

        PRD: "Because forcing the posture to `FROZEN` is an escalation out of `OPEN`, the same step also fires the revalidation cascade: every `ADEQUATE` substantiation dossier of the establishment moves to `REVALIDATION_REQUIRED` with its listing's `safety_status` following, and each dossier so moved is counted in `revalidation_required_count`."

        Design: Difficulty/transitive_cascade/sweep_lapse_cascades_posture_listing_designation_and_dormancy
        """
        bundle, counters = _lapsed_by_sweep(api)

        assert counters["revalidation_required_count"] == 1
        assert counters["overdue_event_count"] == 0
        assert counters["closed_vai_count"] == 0
        assert counters["escalated_oai_count"] == 0

        dossier = X.read_substantiation(api, bundle["dossier"]["id"])
        assert dossier["status"] == K.SUBSTANTIATION_STATUS_REVALIDATION_REQUIRED
        assert X.read_listing(api, bundle["listing_id"])["safety_status"] == (
            K.SAFETY_STATUS_REVALIDATION_REQUIRED
        )

    def test_the_lapse_writes_a_posture_change_and_one_transition_for_the_listing(self, api):
        """The ledger takes the posture move, whose after value is the frozen posture, and
        then exactly one transition entry naming the suspended listing.

        PRD: "The ledger receives one `POSTURE_CHANGE` entry carrying `posture_before` and `posture_after` `FROZEN`, followed by one `STATE_TRANSITION` entry per suspended listing in the same hop-2 order."

        Design: Difficulty/transitive_cascade/sweep_lapse_cascades_posture_listing_designation_and_dormancy
        """
        bundle, _counters = _lapsed_by_sweep(api)

        entries = X.ledger_entries(api, bundle["facility_id"])
        A.assert_ledger_sequence_numbers(entries)

        posture_entries = A.find_entries(entries, K.ENTRY_TYPE_POSTURE_CHANGE)
        assert len(posture_entries) == 1
        assert posture_entries[0]["posture_after"] == K.POSTURE_FROZEN

        position = entries.index(posture_entries[0])
        following = entries[position + 1]
        assert following["entry_type"] == K.ENTRY_TYPE_STATE_TRANSITION
        assert following["subject_entity"] == "ProductListing"
        assert following["subject_id"] == bundle["listing_id"]

    def test_a_second_sweep_at_the_same_clock_moves_nothing(self, api):
        """The sweep is an observation of the clock, so a second run with the clock untouched
        reports every counter at zero.

        PRD: "Running it twice without moving the logical clock in between yields a second response whose every counter is zero and whose `swept_at` equals the clock, because each of the three steps selects only records whose state still admits the transition, and the first run has already moved them all."

        Design: Difficulty/transitive_cascade/sweep_lapse_cascades_posture_listing_designation_and_dormancy
        """
        bundle, _counters = _lapsed_by_sweep(api)

        second = X.run_sweep(api)

        A.assert_sweep_counters(second)
        assert second["swept_at"] == "2028-08-01T00:00:00Z"
        assert X.read_facility(api, bundle["facility_id"])["registration_status"] == (
            K.REGISTRATION_STATUS_LAPSED
        )
