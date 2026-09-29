"""Derived quantities computed from their own pinned inputs: the biennial date
arithmetic and its day-clamp, the input set that the points total draws from,
the two constants inside the adequacy score, the disclosure exemption, and the
tier that the recovery rate reads from its provisional value rather than its
final one.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    OFFICER_2_HEADERS,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_facility_registrant_headers,
)
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


class TestTheInitialWindowClampsALeapDayAnchor:
    """A term anchored on 29 February resolves against a shorter target month."""

    def _establishment_approved_on_a_leap_day(self, api):
        X.set_clock(api, "2028-02-29T00:00:00Z")
        return X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )

    def test_the_anchor_day_falls_back_to_the_last_day_the_month_admits(self, api):
        """Approval on a leap day starts the term there, and the two-year anchor lands in a
        February that has no twenty-ninth, so the day clamps down and the closed-closed window
        ends the day before the clamped anchor.

        PRD: "Take the start date's year and add two; keep the start date's month; take the day of month, but if that day does not exist in the target month, clamp it down to the last day that does exist in that month."
        PRD: "That anchor date is the first day *after* coverage, so `period_end` is the anchor date minus one day — registration periods are closed-closed, meaning both `period_start` and `period_end` are days inside the coverage window."

        Design: Corner/calculations/initial_period_end_clamps_a_leap_day_anchor_to_february_twenty_seventh
        """
        facility = self._establishment_approved_on_a_leap_day(api)

        assert facility["current_period_start"] == "2028-02-29"
        assert facility["current_period_end"] == "2030-02-27"

    def test_the_two_derived_dates_inherit_the_clamped_end(self, api):
        """Both derived dates are measured from the clamped end rather than from the anchor, and
        the establishment's mirror and its single active period agree on all four.

        PRD: "From `period_end`, two further dates fall out: `renewal_window_open_date` is 90 days before `period_end`, and `grace_end_date` is 60 days after `period_end`."
        PRD: "Each period also records the establishment it belongs to through its `facility_id`, and carries a `sequence_index` that is 1 for the initial period and one greater than its predecessor's for every successor."

        Design: Corner/calculations/initial_period_end_clamps_a_leap_day_anchor_to_february_twenty_seventh
        """
        facility = self._establishment_approved_on_a_leap_day(api)

        A.assert_facility_period_mirror(
            facility, "2028-02-29", "2030-02-27", "2029-11-29", "2030-04-28"
        )

        periods, meta = validate_paginated(
            api.list_registration_periods(facility["id"], REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 1
        period = periods[0]
        assert period["facility_id"] == facility["id"]
        assert period["period_kind"] == K.PERIOD_KIND_INITIAL
        assert period["sequence_index"] == 1
        assert period["status"] == K.PERIOD_STATUS_ACTIVE
        A.assert_period_bounds(period, "2028-02-29", "2030-02-27", "2029-11-29", "2030-04-28")


def _file_standard_renewal(api, facility_id):
    """The registrant files the ordinary renewal for its own establishment."""
    return get_success_data(
        api.file_renewal(
            facility_id, F.renewal_payload(K.RENEWAL_KIND_STANDARD),
            make_facility_registrant_headers(facility_id),
        )
    )


class TestARenewalMintsAGapFreeSuccessor:
    """The cadence follows the predecessor's end date, never the filing date."""

    def test_the_successor_starts_the_day_after_coverage_ended(self, api):
        """Filed two and a half months early, the successor still begins the day after the
        predecessor's coverage ended, so the biennial cadence neither drifts nor leaves a gap.

        PRD: "The successor's `period_start` is always the predecessor's `period_end` plus one day — the cadence is gap-free and never drifts, even when the filing itself arrives late — and its `period_end`, `renewal_window_open_date` and `grace_end_date` follow the same two-year derivation described above."
        PRD: "Consider the canonical sequence: a period running 2026-08-01 through 2028-07-31 is renewed on 2028-06-15, inside its window; the successor starts 2028-08-01, ends 2030-07-31, opens its own renewal window on 2030-05-02, has `grace_end_date` 2030-09-29, `period_kind` `RENEWAL` and `sequence_index` 2."

        Design: Corner/calculations/renewal_inside_the_window_mints_a_contiguous_gap_free_successor_period
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        A.assert_facility_period_mirror(
            facility, K.CANONICAL_PERIOD_START, K.CANONICAL_PERIOD_END,
            "2028-05-02", "2028-09-29",
        )

        X.set_clock(api, "2028-06-15T00:00:00Z")
        successor = _file_standard_renewal(api, facility["id"])

        A.assert_period_bounds(successor, "2028-08-01", "2030-07-31", "2030-05-02", "2030-09-29")
        assert successor["period_kind"] == K.PERIOD_KIND_RENEWAL
        assert successor["sequence_index"] == 2
        assert successor["status"] == K.PERIOD_STATUS_ACTIVE

    def test_the_establishment_mirrors_the_new_window_and_counts_a_second_cycle(self, api):
        """The renewal is the self-loop taken from a still-registered establishment, so the
        status is unchanged while the cycle count and all four mirrored dates move on.

        PRD: "`sequence_index` is the predecessor's plus one, `registration_cycle_count` rises by 1, `registration_status` is set to `REGISTERED`, the establishment's four derived date fields and its `compliance_posture` are recomputed, a `STATE_TRANSITION` ledger entry recording that the renewal was accepted is appended, and the establishment's `version` rises by 1."
        PRD: "But a registrant may also renew while the establishment is still `REGISTERED` — the renewal window has opened and the sweep has not yet flipped the advisory status — and that produces the self-loop `REGISTERED → REGISTERED`, with exactly the same period-minting side effects and the same increment to `registration_cycle_count`."

        Design: Corner/calculations/renewal_inside_the_window_mints_a_contiguous_gap_free_successor_period
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        assert facility["registration_cycle_count"] == 1

        X.set_clock(api, "2028-06-15T00:00:00Z")
        _file_standard_renewal(api, facility["id"])

        after = X.read_facility(api, facility["id"])
        assert after["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
        assert after["registration_cycle_count"] == 2
        A.assert_facility_period_mirror(
            after, "2028-08-01", "2030-07-31", "2030-05-02", "2030-09-29"
        )
        assert after["version"] == facility["version"] + 1

    def test_the_predecessor_is_expired_by_the_minting_of_its_successor(self, api):
        """Exactly one window is in force at a time: the old period is retired the moment the
        new one is minted, and the two are separated cleanly by the status filter.

        PRD: "A period's `status` is `ACTIVE` while it is the coverage window in force and becomes `EXPIRED` either when a successor period is minted or when the sweep observes that the establishment has run past `grace_end_date` without renewing."
        PRD: "Registration periods are read back in ascending `sequence_index` order — the audit trail of the biennial cadence — and the listing may be narrowed with a `status` filter."

        Design: Corner/calculations/renewal_inside_the_window_mints_a_contiguous_gap_free_successor_period
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        X.set_clock(api, "2028-06-15T00:00:00Z")
        _file_standard_renewal(api, facility["id"])

        expired, _expired_meta = validate_paginated(
            api.list_registration_periods(
                facility["id"], REVIEWER_HEADERS, {"status": K.PERIOD_STATUS_EXPIRED}
            )
        )
        assert [row["sequence_index"] for row in expired] == [1]

        active, _active_meta = validate_paginated(
            api.list_registration_periods(
                facility["id"], REVIEWER_HEADERS, {"status": K.PERIOD_STATUS_ACTIVE}
            )
        )
        assert [row["sequence_index"] for row in active] == [2]

        both, _both_meta = validate_paginated(
            api.list_registration_periods(facility["id"], REVIEWER_HEADERS)
        )
        assert [row["sequence_index"] for row in both] == [1, 2]


def _consumer_listing_at_the_receipt_instant(api):
    """A consumer leave-on product, with the clock standing at 2026-08-05."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Aster Labs Newark",
            "owner_operator_name": "Aster Holdings LLC",
            "state_or_province": "NJ",
        },
        person_overrides={"legal_name": "Aster Brands Inc"},
        listing_overrides={
            "product_name": "Aster Blush Powder",
            "category_code": "07A",
            "label_contact_type": K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            "label_contact_value": "safety@aster.example",
        },
    )
    X.set_clock(api, "2026-08-05T08:00:00Z")
    return bundle


class TestOnlyPricedEventsEnterTheEstablishmentTotal:
    """Three events on one product, and only one of them costs anything."""

    def _three_events_one_of_them_reported(self, api):
        bundle = _consumer_listing_at_the_receipt_instant(api)
        bundle["retained"] = X.record_retained_event(
            api, bundle["listing_id"], bundle["agent"], "2026-08-05T00:00:00Z",
            event_description="Transient stinging, resolved same day", outcome_code="NONE",
        )
        bundle["due"] = X.record_serious_event(
            api, bundle["listing_id"], bundle["agent"], "2026-08-05T00:00:00Z",
            event_description="Chemical burn requiring urgent care",
            outcome_code="HOSPITALIZATION",
        )
        bundle["reported_event"] = X.record_serious_event(
            api, bundle["listing_id"], bundle["agent"], "2026-08-05T00:00:00Z",
            event_description="Facial swelling with persistent scarring",
            outcome_code="DISFIGUREMENT",
        )
        bundle["reported"] = X.file_report(
            api, bundle["reported_event"]["id"], bundle["agent"]
        )
        return bundle

    def test_a_retained_event_carries_no_deadline_and_no_price(self, api):
        """A non-serious intake is filed away rather than reported: it has no clock, no price and
        the shorter consumer retention horizon.

        PRD: "A `NON_SERIOUS` intake takes the `RECORDED → RETAINED` edge: `deadline_basis_at` and `deadline_at` stay null, `event_points` stays 0.00, no open-event counter moves, the establishment's `serious_event_points` and `compliance_posture` are untouched, and `retention_until` is set to the calendar date of `received_at` plus three years — or plus six years when the listing is `professional_use_only`, since professional-channel complaints are held for the longer term."

        Design: Corner/calculations/points_input_set_excludes_retained_and_still_unreported_events
        """
        bundle = _consumer_listing_at_the_receipt_instant(api)

        retained = X.record_retained_event(
            api, bundle["listing_id"], bundle["agent"], "2026-08-05T00:00:00Z",
            event_description="Transient stinging, resolved same day", outcome_code="NONE",
        )

        assert retained["report_status"] == K.EVENT_STATUS_RETAINED
        assert retained["deadline_basis_at"] is None
        assert retained["deadline_at"] is None
        A.assert_two_decimal_value(retained["event_points"], 0.00, "event_points")
        assert retained["retention_until"] == "2029-08-05"
        assert X.read_facility(api, bundle["facility_id"])["open_serious_event_count"] == 0

    def test_an_unreported_serious_event_is_an_obligation_without_a_price(self, api):
        """Inside its deadline a serious event costs the establishment nothing at all, which is
        the asymmetry the points engine is built on.

        PRD: "An event contributes only while its `report_status` is `REPORTED_TIMELY`, `REPORTED_LATE` or `REPORT_OVERDUE`; events that are `RECORDED`, `RETAINED` or still `REPORT_DUE` contribute exactly 0.00, which is the important asymmetry — a serious event inside its deadline costs the establishment nothing, and the cost appears the moment the deadline is missed or the report is filed."

        Design: Corner/calculations/points_input_set_excludes_retained_and_still_unreported_events
        """
        bundle = _consumer_listing_at_the_receipt_instant(api)

        due = X.record_serious_event(
            api, bundle["listing_id"], bundle["agent"], "2026-08-05T00:00:00Z",
            event_description="Chemical burn requiring urgent care",
            outcome_code="HOSPITALIZATION",
        )

        assert due["report_status"] == K.EVENT_STATUS_REPORT_DUE
        A.assert_two_decimal_value(due["event_points"], 0.00, "event_points")
        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 0.00, "serious_event_points")
        assert facility["open_serious_event_count"] == 1

    def test_the_total_is_exactly_the_one_reported_event(self, api):
        """Three events sit under one product and the establishment's total is the price of the
        single reported one; the counter reflects only the serious events still awaiting a report.

        PRD: "Each event carries its own `event_points`, and the establishment's `serious_event_points` is the sum of them."
        PRD: "An establishment's `open_serious_event_count` is at all times the number of its listings' events that are `SERIOUS` and whose `report_status` is `REPORT_DUE` or `REPORT_OVERDUE`, and the listing-level counter is the same tally restricted to that listing."

        Design: Corner/calculations/points_input_set_excludes_retained_and_still_unreported_events
        """
        bundle = self._three_events_one_of_them_reported(api)

        A.assert_two_decimal_value(bundle["reported"]["event_points"], 2.00, "event_points")

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 2.00, "serious_event_points")
        assert facility["open_serious_event_count"] == 1
        assert facility["compliance_posture"] == K.POSTURE_OPEN

    def test_the_event_list_separates_the_three_by_status_and_seriousness(self, api):
        """The two filters cut the same three rows along different axes, which is how a caller
        tells a filed-away complaint from an outstanding reporting obligation.

        PRD: "All five roles may read a listing's events, newest first, and the list narrows on `seriousness` and on `report_status`; each row exposes `deadline_at`, `lateness_days`, `event_points` and `retention_until` alongside the narrative."

        Design: Corner/calculations/points_input_set_excludes_retained_and_still_unreported_events
        """
        bundle = self._three_events_one_of_them_reported(api)

        retained_rows, _retained_meta = validate_paginated(
            api.list_adverse_events(
                bundle["listing_id"], bundle["agent"],
                {"report_status": K.EVENT_STATUS_RETAINED},
            )
        )
        assert A.ids_of(retained_rows) == [bundle["retained"]["id"]]

        serious_rows, _serious_meta = validate_paginated(
            api.list_adverse_events(
                bundle["listing_id"], bundle["agent"],
                {"seriousness": K.SERIOUSNESS_SERIOUS},
            )
        )
        assert sorted(A.ids_of(serious_rows)) == sorted(
            [bundle["due"]["id"], bundle["reported_event"]["id"]]
        )


class TestReclassificationRebasesTheReportClock:
    """The later basis instant governs the deadline; the receipt still governs retention."""

    def _reclassified_at_the_end_of_august(self, api):
        bundle = _consumer_listing_at_the_receipt_instant(api)
        retained = X.record_retained_event(
            api, bundle["listing_id"], bundle["agent"], "2026-08-05T00:00:00Z",
            event_description="Transient stinging, resolved same day", outcome_code="NONE",
        )
        bundle["retention_before"] = retained["retention_until"]
        X.set_clock(api, "2026-08-25T09:30:00Z")
        bundle["escalated"] = get_success_data(
            api.reclassify_adverse_event(
                retained["id"], F.reclassify_payload(K.SERIOUSNESS_SERIOUS), REVIEWER_HEADERS
            )
        )
        return bundle

    def test_the_deadline_is_measured_from_the_reclassification_not_the_receipt(self, api):
        """Escalated twenty days after receipt, the event is given a fresh fifteen days from the
        decision to escalate rather than a deadline that has already expired.

        PRD: "Reclassification takes the `RETAINED → REPORT_DUE` edge, sets `seriousness` to `SERIOUS` and `reclassified_at` to the logical clock, and **rebases the report clock on the reclassification instant**: `deadline_basis_at` becomes `reclassified_at`, not `received_at`, and `deadline_at` is recomputed from that later basis."
        PRD: "An event received on 2026-08-05 and reclassified at 2026-08-25T09:30:00Z is due 2026-09-09T23:59:59.999Z, not 2026-08-20 — the sponsor is not retroactively in breach of a deadline that predates the decision to escalate."

        Design: Corner/calculations/reclassified_event_rebases_its_deadline_and_extends_its_retention
        """
        bundle = self._reclassified_at_the_end_of_august(api)
        escalated = bundle["escalated"]

        assert escalated["report_status"] == K.EVENT_STATUS_REPORT_DUE
        assert escalated["seriousness"] == K.SERIOUSNESS_SERIOUS
        assert escalated["reclassified_at"] == "2026-08-25T09:30:00Z"
        assert escalated["deadline_basis_at"] == "2026-08-25T09:30:00Z"
        A.assert_deadline_at_end_of_day(escalated["deadline_at"], "2026-09-09")

    def test_the_retention_horizon_stretches_but_stays_anchored_on_the_receipt(self, api):
        """The file is now kept for the longer serious term, yet that term is still counted from
        the day the complaint arrived, so the horizon does not slide with the escalation.

        PRD: "Both open-event counters rise by 1, and `retention_until` is extended to the six-year term — but that term is measured from `received_at`, never from `reclassified_at`, so the retention horizon does not move with the reclassification."

        Design: Corner/calculations/reclassified_event_rebases_its_deadline_and_extends_its_retention
        """
        bundle = self._reclassified_at_the_end_of_august(api)

        assert bundle["retention_before"] == "2029-08-05"
        assert bundle["escalated"]["retention_until"] == "2032-08-05"
        assert X.read_facility(api, bundle["facility_id"])["open_serious_event_count"] == 1
        assert X.read_listing(api, bundle["listing_id"])["open_serious_event_count"] == 1

    def test_the_rebased_event_is_out_of_the_points_input_set_again(self, api):
        """Escalation raises an obligation, not a cost: the event is back to being due and so
        contributes nothing to the establishment's total.

        PRD: "Because rebasing can only ever push a deadline later, reclassification never creates lateness by itself."

        Design: Corner/calculations/reclassified_event_rebases_its_deadline_and_extends_its_retention
        """
        bundle = self._reclassified_at_the_end_of_august(api)

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 0.00, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_OPEN

        due_rows, _meta = validate_paginated(
            api.list_adverse_events(
                bundle["listing_id"], bundle["agent"],
                {"report_status": K.EVENT_STATUS_REPORT_DUE},
            )
        )
        assert A.ids_of(due_rows) == [bundle["escalated"]["id"]]


CANONICAL_PASS_SCORE = 65.00
PENALISED_SCORE = 50.00


def _dossier_over_a_data_gap_ingredient(api):
    """The canonical 40.00 + 25.00 dossier, submitted over an ingredient list that
    carries one unresolved toxicological gap."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Aster Labs Newark",
            "owner_operator_name": "Aster Holdings LLC",
            "state_or_province": "NJ",
        },
        person_overrides={"legal_name": "Aster Brands Inc"},
        listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
    )
    X.add_ingredient(
        api, bundle["listing_id"], bundle["agent"],
        F.data_gap_ingredient_payload(inci_name="PROPRIETARY BOTANICAL EXTRACT 44"),
    )
    dossier = X.open_dossier(
        api, bundle["listing_id"], bundle["agent"], assessor_name="Dr. Imani Ferro"
    )
    X.attach_items(api, dossier["id"], bundle["agent"], X.PASSING_EVIDENCE)
    bundle["submitted"] = X.submit_dossier(api, dossier["id"], bundle["agent"])
    bundle["dossier_id"] = dossier["id"]
    return bundle


class TestOneDataGapIngredientCostsTheDossierFifteenPoints:
    """The gap both forbids the triage variant and prices the substantive one."""

    def test_the_gap_flag_is_re_derived_from_the_ingredient_list_at_submission(self, api):
        """The dossier was opened after the gap ingredient was added and submission refreshes
        the flag from the current ingredient set, so the first round arrives already marked.

        PRD: "Its `data_gap_present` is set from the listing's ingredients: it is true exactly when at least one ingredient of the listing carries `is_data_gap_flag`."
        PRD: "A successful submission moves the dossier to `SUBMITTED`, increments `revision_round` by exactly 1 — it counts every entry into `SUBMITTED`, including re-submissions after a deficiency or a revalidation demand, and ranges from 0 to 99 — sets the listing's `safety_status` to `UNDER_SUBSTANTIATION`, refreshes `data_gap_present` from the listing's current ingredient set, recomputes `marketable`, and increments both the dossier's `version` and the listing's `version` by 1."

        Design: Corner/calculations/data_gap_penalty_pushes_a_sixty_five_point_dossier_to_deficient
        """
        bundle = _dossier_over_a_data_gap_ingredient(api)

        submitted = bundle["submitted"]
        assert submitted["data_gap_present"] is True
        assert submitted["revision_round"] == 1
        assert submitted["status"] == K.SUBSTANTIATION_STATUS_SUBMITTED
        assert X.read_listing(api, bundle["listing_id"])["safety_status"] == (
            K.SAFETY_STATUS_UNDER_SUBSTANTIATION
        )

    def test_the_triage_variant_is_refused_outright_and_changes_nothing(self, api):
        """A screening pass may not clear a product with an unresolved gap, and the refusal
        leaves the dossier awaiting a decision with no mode recorded.

        PRD: "When `data_gap_present` is true the mode is not free: only `FULL` is admissible, and a `SCREENING` decision on a data-gap dossier is refused with `ERR_FULL_REVIEW_REQUIRED_FOR_DATA_GAP` (HTTP 422) — a screening pass may not clear a product whose ingredient list carries an unresolved toxicological gap."

        Design: Corner/calculations/data_gap_penalty_pushes_a_sixty_five_point_dossier_to_deficient
        """
        bundle = _dossier_over_a_data_gap_ingredient(api)

        validate_error(
            api.decide_substantiation_review(
                bundle["dossier_id"],
                F.review_decision_payload(K.REVIEW_MODE_SCREENING),
                REVIEWER_HEADERS,
            ),
            E.ERR_FULL_REVIEW_REQUIRED_FOR_DATA_GAP,
        )

        dossier = X.read_substantiation(api, bundle["dossier_id"])
        assert dossier["status"] == K.SUBSTANTIATION_STATUS_SUBMITTED
        assert dossier["review_mode"] is None
        assert dossier["adequacy_score"] is None
        assert dossier["decided_at"] is None

    def test_the_penalty_turns_the_canonical_pass_into_a_deficiency(self, api):
        """The very evidence that scores 65.00 and passes on a clean ingredient list scores
        50.00 here, because the substantive variant subtracts the gap penalty from the sum of
        the capped group totals.

        PRD: "Third, when `data_gap_present` is true, 15.00 is subtracted from the sum of the capped group totals; the result is floored at 0.00 so the score is never negative, and the final total is rounded half up to two decimal places."
        PRD: "In either mode a score of **60.00 or more** rules the dossier `ADEQUATE` and anything below 60.00 rules it `DEFICIENT`; the pass mark is inclusive at the boundary."

        Design: Corner/calculations/data_gap_penalty_pushes_a_sixty_five_point_dossier_to_deficient
        """
        bundle = _dossier_over_a_data_gap_ingredient(api)

        decided = X.decide_dossier(api, bundle["dossier_id"], K.REVIEW_MODE_FULL)

        A.assert_two_decimal_value(
            decided["adequacy_score"], CANONICAL_PASS_SCORE - K.DATA_GAP_PENALTY, "adequacy_score"
        )
        A.assert_two_decimal_value(decided["adequacy_score"], PENALISED_SCORE, "adequacy_score")
        assert decided["status"] == K.SUBSTANTIATION_STATUS_DEFICIENT
        assert decided["review_mode"] == K.REVIEW_MODE_FULL
        assert decided["full_reviewer_user_id"] == "RVW-1"
        assert decided["screening_reviewer_user_id"] is None

    def test_the_deficiency_unseats_the_safety_dimension_and_leaves_the_other_alone(self, api):
        """The product's safety dimension fails and it is not marketable, yet its submission
        dimension has not moved at all.

        PRD: "The dossier then moves `SUBMITTED → ADEQUATE` or `SUBMITTED → DEFICIENT`, the listing's `safety_status` becomes `SUBSTANTIATED` or `SUBSTANTIATION_FAILED` correspondingly, `marketable` is recomputed, one `STATE_TRANSITION` ledger entry is appended against the listing as its `subject_entity`, and the `version` of both the dossier and the listing rises by 1."
        PRD: "A deficiency verdict does **not** touch `listing_status`."

        Design: Corner/calculations/data_gap_penalty_pushes_a_sixty_five_point_dossier_to_deficient
        """
        bundle = _dossier_over_a_data_gap_ingredient(api)
        X.decide_dossier(api, bundle["dossier_id"], K.REVIEW_MODE_FULL)

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_SUBSTANTIATION_FAILED
        assert listing["marketable"] is False
        assert listing["listing_status"] == K.LISTING_STATUS_DRAFT


HISTORICAL_ITEM_VALUE = 10.00
HISTORICAL_ITEM_COUNT = 6


def _dossier_of_six_historical_monographs(api):
    """Six historical-use volumes, each attested by a board-certified toxicologist:
    60.00 raw, and one single evidence class."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Aster Labs Newark",
            "owner_operator_name": "Aster Holdings LLC",
            "state_or_province": "NJ",
        },
        person_overrides={"legal_name": "Aster Brands Inc"},
        listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
    )
    dossier = X.open_dossier(
        api, bundle["listing_id"], bundle["agent"],
        assessor_name="Dr. Imani Ferro",
        assessment_basis=K.ASSESSMENT_BASIS_PANEL_MONOGRAPH,
    )
    X.attach_items(
        api, dossier["id"], bundle["agent"],
        [(K.EVIDENCE_HISTORICAL, K.CREDENTIAL_BOARD_CERTIFIED)] * HISTORICAL_ITEM_COUNT,
    )
    bundle["submitted"] = X.submit_dossier(api, dossier["id"], bundle["agent"])
    bundle["dossier_id"] = dossier["id"]
    return bundle


class TestOneEvidenceClassCannotCarryADossierOnItsOwn:
    """Six ten-point volumes group to sixty and are held at the class cap of forty."""

    def test_the_single_class_is_capped_below_the_pass_mark(self, api):
        """Nothing but the cap is in play — there is no gap ingredient and no read-across
        discount — and the six-item group is still held to 40.00, which fails.

        PRD: "Second, the item values are grouped by `evidence_type`, summed within each group, and each group total is capped at 40.00, so no single class of evidence can carry a dossier on its own."
        PRD: "And six `HISTORICAL_USE_DOSSIER` items attested by board-certified toxicologists sum to 60.00 raw, which would pass, but under `FULL` the single class is capped at 40.00 and the dossier is deficient."

        Design: Corner/calculations/evidence_type_cap_holds_six_ten_point_items_at_forty
        """
        bundle = _dossier_of_six_historical_monographs(api)
        assert bundle["submitted"]["data_gap_present"] is False

        decided = X.decide_dossier(api, bundle["dossier_id"], K.REVIEW_MODE_FULL)

        A.assert_two_decimal_value(
            decided["adequacy_score"], K.EVIDENCE_CLASS_CAP, "adequacy_score"
        )
        assert decided["status"] == K.SUBSTANTIATION_STATUS_DEFICIENT

    def test_each_item_is_still_recorded_at_its_own_uncapped_worth(self, api):
        """The cap belongs to the group, so every one of the six rows reports the full ten
        points it is individually worth even though their sum was clipped.

        PRD: "and it writes both `screening_contribution` and `full_contribution` onto every evidence item of the dossier, so a client can inspect what each item would be worth under either variant — `full_contribution` holds the item's value after any read-across discount but **before** the per-class cap is applied, since the cap is a property of the group rather than of the item."

        Design: Corner/calculations/evidence_type_cap_holds_six_ten_point_items_at_forty
        """
        bundle = _dossier_of_six_historical_monographs(api)
        X.decide_dossier(api, bundle["dossier_id"], K.REVIEW_MODE_FULL)

        rows, _meta = validate_paginated(
            api.list_review_items(
                bundle["dossier_id"], REVIEWER_HEADERS, {"limit": K.MAX_LIMIT}
            )
        )
        assert len(rows) == HISTORICAL_ITEM_COUNT
        for row in rows:
            assert row["evidence_type"] == K.EVIDENCE_HISTORICAL
            A.assert_two_decimal_value(
                row["full_contribution"], HISTORICAL_ITEM_VALUE, "full_contribution"
            )
            A.assert_two_decimal_value(
                row["screening_contribution"], HISTORICAL_ITEM_VALUE, "screening_contribution"
            )

    def test_the_uncapped_variant_passes_the_very_same_evidence(self, api):
        """Scored under triage the identical six items sum to sixty and clear the mark, which
        is what makes the cap — and not the evidence — the reason for the deficiency.

        PRD: "Under `SCREENING` the score is simply the sum of those per-item values, the total itself rounded half up to two decimal places. There is no per-class cap, no read-across discount, no data-gap penalty and no upper ceiling — a screening score may exceed 100.00."

        Design: Corner/calculations/evidence_type_cap_holds_six_ten_point_items_at_forty
        """
        bundle = _dossier_of_six_historical_monographs(api)

        screened = X.decide_dossier(api, bundle["dossier_id"], K.REVIEW_MODE_SCREENING)

        A.assert_two_decimal_value(
            screened["adequacy_score"],
            HISTORICAL_ITEM_VALUE * HISTORICAL_ITEM_COUNT,
            "adequacy_score",
        )
        assert screened["status"] == K.SUBSTANTIATION_STATUS_ADEQUATE
        assert X.read_listing(api, bundle["listing_id"])["safety_status"] == (
            K.SAFETY_STATUS_SUBSTANTIATED
        )


HIGH_ALLERGEN_CONCENTRATION = 0.5000


def _one_professional_and_one_consumer_leave_on_product(api):
    """Two leave-on products under one designee: a professional-use-only peel and an
    ordinary consumer blush."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Aster Labs Newark",
            "owner_operator_name": "Aster Holdings LLC",
            "state_or_province": "NJ",
        },
        person_overrides={"legal_name": "Aster Brands Inc"},
        listing_overrides={
            "product_name": "Aster Blush Powder",
            "category_code": "07A",
            "label_contact_type": K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            "label_contact_value": "safety@aster.example",
        },
    )
    professional = get_success_data(
        api.create_listing(
            F.professional_listing_payload(
                bundle["facility_id"], bundle["person_id"],
                product_name="Aster Pro Peel 30",
                label_contact_type=K.LABEL_CONTACT_DOMESTIC_PHONE,
                label_contact_value="+1-202-555-0110",
            ),
            bundle["agent"],
        )
    )
    bundle["professional_id"] = professional["id"]
    return bundle


class TestTheProfessionalChannelIsExemptFromAllergenDisclosure:
    """The same allergen at the same concentration, and two opposite verdicts."""

    def test_the_exemption_overrides_a_concentration_far_above_the_threshold(self, api):
        """At 0.5000 percent the allergen is five hundred times the leave-on threshold, yet the
        professional-use row is not disclosure-required at all, because the exemption is one of
        the three clauses of the per-ingredient derivation rather than a later override.

        PRD: "For each ingredient of the listing, `disclosure_required` is true when all three of the following hold: `is_fragrance_allergen` is true, `concentration_pct` is at or above the applicable threshold — the comparison is inclusive, and it is made against the stored four-decimal value — and the listing's `professional_use_only` is false."
        PRD: "Professional-use products are exempt from fragrance-allergen label disclosure entirely, which is why the third clause is part of the per-ingredient derivation rather than a separate rule."

        Design: Corner/calculations/professional_use_only_listing_exempts_its_allergens_from_disclosure
        """
        bundle = _one_professional_and_one_consumer_leave_on_product(api)

        row = X.add_ingredient(
            api, bundle["professional_id"], bundle["agent"],
            F.allergen_ingredient_payload(
                inci_name="LINALOOL", concentration_pct=HIGH_ALLERGEN_CONCENTRATION,
                label_disclosed=False,
            ),
        )

        assert row["is_fragrance_allergen"] is True
        assert row["label_disclosed"] is False
        assert row["disclosure_required"] is False

        professional = X.read_listing(api, bundle["professional_id"])
        assert professional["professional_use_only"] is True
        assert professional["undisclosed_allergen_count"] == 0
        assert professional["allergen_disclosure_complete"] is True

    def test_the_identical_row_on_the_consumer_product_is_disclosure_required(self, api):
        """The consumer blush carries the very same undisclosed allergen at the very same
        concentration and is therefore incomplete, which isolates the professional-use flag as
        the only thing separating the two products.

        PRD: "The disclosure threshold is a concentration of **0.001 percent** for a `LEAVE_ON` listing and **0.01 percent** for a `RINSE_OFF` listing."
        PRD: "From those flags, `undisclosed_allergen_count` is the number of ingredients whose `disclosure_required` is true while `label_disclosed` is false, and `allergen_disclosure_complete` is true exactly when that count is 0."

        Design: Corner/calculations/professional_use_only_listing_exempts_its_allergens_from_disclosure
        """
        bundle = _one_professional_and_one_consumer_leave_on_product(api)
        X.add_ingredient(
            api, bundle["professional_id"], bundle["agent"],
            F.allergen_ingredient_payload(
                inci_name="LINALOOL", concentration_pct=HIGH_ALLERGEN_CONCENTRATION,
                label_disclosed=False,
            ),
        )

        consumer_row = X.add_ingredient(
            api, bundle["listing_id"], bundle["agent"],
            F.allergen_ingredient_payload(
                inci_name="LINALOOL", concentration_pct=HIGH_ALLERGEN_CONCENTRATION,
                label_disclosed=False,
            ),
        )

        assert consumer_row["disclosure_required"] is True
        consumer = X.read_listing(api, bundle["listing_id"])
        assert consumer["professional_use_only"] is False
        assert consumer["undisclosed_allergen_count"] == 1
        assert consumer["allergen_disclosure_complete"] is False

    def test_the_allergen_verdict_says_nothing_about_the_safety_dimension(self, api):
        """Neither product has a dossier, so both remain unsubstantiated and non-marketable
        whichever way their allergen tally went.

        PRD: "The vacuous case must resolve to complete, not incomplete: a listing with no ingredients at all, a listing whose fragrance allergens all sit below the threshold, and a professional-use-only listing all report `undisclosed_allergen_count` 0 and `allergen_disclosure_complete` true."

        Design: Corner/calculations/professional_use_only_listing_exempts_its_allergens_from_disclosure
        """
        bundle = _one_professional_and_one_consumer_leave_on_product(api)
        for listing_id in (bundle["professional_id"], bundle["listing_id"]):
            X.add_ingredient(
                api, listing_id, bundle["agent"],
                F.allergen_ingredient_payload(
                    inci_name="LINALOOL", concentration_pct=HIGH_ALLERGEN_CONCENTRATION,
                    label_disclosed=False,
                ),
            )

        for listing_id in (bundle["professional_id"], bundle["listing_id"]):
            listing = X.read_listing(api, listing_id)
            assert listing["safety_status"] == K.SAFETY_STATUS_UNSUBSTANTIATED
            assert listing["marketable"] is False


SHIPPED_UNITS = 1000
VERIFIED_UNITS = 880
PROVISIONAL_RATE = 88.00
MID_TIER_CREDIT_PCT = 3
ADJUSTED_DENOMINATOR = 970
FINAL_RATE = 90.72


def _withdrawal_with_eight_hundred_and_eighty_units_verified(api):
    """One thousand units shipped to a retailer, eight hundred and eighty of them
    verified as returned under an executing recall."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Aster Labs Newark",
            "owner_operator_name": "Aster Holdings LLC",
            "state_or_province": "NJ",
        },
        person_overrides={"legal_name": "Aster Brands Inc"},
        listing_overrides={
            "product_name": "Aster Blush Powder",
            "category_code": "07A",
            "label_contact_type": K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            "label_contact_value": "safety@aster.example",
            "lot_authorized_units": 5000,
        },
    )
    bundle = X.withdrawal_with_produced_records(
        api, bundle,
        specs=[{"lot_code": "LOT-C", "ship_date": "2026-08-05", "delivery_date": "2026-08-08",
                "units_shipped": SHIPPED_UNITS, "consignee_name": "Gulf Coast Retail Group",
                "consignee_class": "RETAIL"}],
        officer=OFFICER_HEADERS,
    )
    bundle["record_after_return"] = X.post_recovery(
        api, bundle["withdrawal_id"], bundle["records"][0]["id"], VERIFIED_UNITS,
        bundle["agent"],
    )
    return bundle


class TestTheUnreachableCreditTierIsPinnedToTheProvisionalRate:
    """Eighty-eight percent verified closes the recall at ninety-point-seven-two."""

    def test_production_and_the_verified_return_settle_the_unit_arithmetic(self, api):
        """The round is holding the whole thousand-unit shipment and one verified return of
        eight hundred and eighty leaves a hundred and twenty units outstanding on the record.

        PRD: "Per record, `units_verified_returned` plus `units_verified_destroyed` plus `units_outstanding` always equals `units_shipped` exactly — no entry may leave a record out of balance."

        Design: Corner/calculations/unreachable_credit_tier_stays_pinned_to_the_provisional_rate
        """
        bundle = _withdrawal_with_eight_hundred_and_eighty_units_verified(api)

        assert bundle["withdrawal"]["shipped_units_total"] == SHIPPED_UNITS
        record = X.read_record(api, bundle["records"][0]["id"])
        assert record["units_verified_returned"] == VERIFIED_UNITS
        assert record["units_outstanding"] == SHIPPED_UNITS - VERIFIED_UNITS

    def test_the_four_pinned_steps_lift_the_rate_across_a_tier_boundary(self, api):
        """The tier is chosen from the provisional 88.00, so the denominator shrinks to 970 and
        the final rate reads 90.72 rather than the 88.00 a fixed-point re-derivation would
        report; every intermediate is stored for inspection.

        PRD: "Step two selects `unreachable_credit_pct` from the **provisional** rate: 0 when it is 90.00 or more, 3 when it is 80.00 or more, and 6 otherwise — the acknowledgement that the harder a recall is going, the more of the distribution chain is genuinely unreachable."
        PRD: "The pinning of step two to the provisional rate is the crux, because step four's denominator shrink **raises** the rate above the provisional figure and can lift it across a tier boundary."

        Design: Corner/calculations/unreachable_credit_tier_stays_pinned_to_the_provisional_rate
        """
        bundle = _withdrawal_with_eight_hundred_and_eighty_units_verified(api)

        reviewed = X.run_effectiveness_check(
            api, bundle["withdrawal_id"], K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )

        assert reviewed["verified_recovered_units"] == VERIFIED_UNITS
        A.assert_two_decimal_value(
            reviewed["provisional_verified_rate"], PROVISIONAL_RATE, "provisional_verified_rate"
        )
        assert reviewed["unreachable_credit_pct"] == MID_TIER_CREDIT_PCT
        assert reviewed["adjusted_denominator_units"] == ADJUSTED_DENOMINATOR
        A.assert_two_decimal_value(
            reviewed["verified_recovery_rate"], FINAL_RATE, "verified_recovery_rate"
        )
        assert reviewed["outstanding_units_total"] == SHIPPED_UNITS - VERIFIED_UNITS
        assert reviewed["effectiveness_verdict"] == K.VERDICT_EFFECTIVE

    def test_the_effective_verdict_closes_the_round_and_the_recall_together(self, api):
        """Because 90.72 clears the threshold the round and its parent recall both go terminal,
        the product's open-recall counter falls to zero and exactly one closure entry is written.

        PRD: "An effective verified review closes the round and the recall together: the withdrawal takes `RECORDS_PRODUCED → CLOSED_EFFECTIVE` or `INTERIM_REVIEWED → CLOSED_EFFECTIVE`, which is terminal; the parent recall moves `EXECUTING → CLOSED_EFFECTIVE`, also terminal, storing `effectiveness_rate_final` as the withdrawal's `verified_recovery_rate`; the listing's `open_recall_count` falls by 1 and its `marketable` flag is recomputed; and one `WITHDRAWAL_CLOSURE` ledger entry is appended against the withdrawal."

        Design: Corner/calculations/unreachable_credit_tier_stays_pinned_to_the_provisional_rate
        """
        bundle = _withdrawal_with_eight_hundred_and_eighty_units_verified(api)
        reviewed = X.run_effectiveness_check(
            api, bundle["withdrawal_id"], K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )

        assert reviewed["status"] == K.WITHDRAWAL_STATUS_CLOSED_EFFECTIVE

        recall = X.read_recall(api, bundle["recall_id"])
        assert recall["status"] == K.RECALL_STATUS_CLOSED_EFFECTIVE
        A.assert_two_decimal_value(
            recall["effectiveness_rate_final"], FINAL_RATE, "effectiveness_rate_final"
        )

        assert X.read_listing(api, bundle["listing_id"])["open_recall_count"] == 0

        closures = X.ledger_entries(
            api, bundle["facility_id"], K.ENTRY_TYPE_WITHDRAWAL_CLOSURE
        )
        assert len(closures) == 1
