"""Endpoint contracts read on their own terms: the one create-then-read pair
with no list endpoint, the all-or-nothing document-production batch, the two
operator capabilities, and a read whose derived projection tracks every source
write rather than a stale snapshot.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    OFFICER_HEADERS,
    OPERATOR_HEADERS,
    REVIEWER_HEADERS,
    make_responsible_person_agent_headers,
)
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X

DESIGNEE_NAME = "Aster Brands Inc"
DESIGNEE_ADDRESS = "12 Market St, Newark NJ 07102"
DESIGNEE_PHONE = "+1-202-555-0110"
DESIGNEE_EMAIL = "safety@aster.example"
DECLARED_CAP = 3
DEFAULT_CAP = 25

SEED_INSTANT = "2026-08-01T00:00:00Z"
LATER_INSTANT = "2026-09-15T12:34:56Z"

LOT_E = "LOT-E"
RETAIL_UNITS = 400
WHOLESALE_UNITS = 250
DRUG_MART_UNITS = 100
ALL_THREE_UNITS = RETAIL_UNITS + WHOLESALE_UNITS + DRUG_MART_UNITS


def _create_designee(api, **overrides):
    """A designee filed by its own agent — the second create-root call in the system."""
    payload = F.responsible_person_payload(
        legal_name=DESIGNEE_NAME,
        us_address_line=DESIGNEE_ADDRESS,
        contact_phone=DESIGNEE_PHONE,
        contact_email=DESIGNEE_EMAIL,
        **overrides,
    )
    return get_success_data(
        api.create_responsible_person(payload, make_responsible_person_agent_headers("seed"))
    )


class TestTheDesigneeReadReturnsExactlyWhatWasFiled:
    """The one entity with a create-then-read pair and no list endpoint."""

    def test_the_read_returns_every_supplied_contact_field_verbatim(self, api):
        """Four contact fields and a declared ceiling go in on the create; the read hands all
        five of them back unchanged.

        PRD: "That party is created as a responsible person by a `ResponsiblePersonAgent`, supplying the `legal_name` that will be printed, a domestic `us_address_line`, a `contact_phone` reachable for adverse-event intake, a `contact_email` for the same purpose, and optionally a `designation_cap` — the ceiling on how many listings this party may simultaneously hold in an active designation slot."

        Design: Corner/endpoints/responsible_person_create_then_read_round_trips_every_stored_field
        """
        created = _create_designee(api, designation_cap=DECLARED_CAP)
        A.assert_identity_fields(created, "responsible person")

        read = X.read_responsible_person(api, created["id"])

        assert read["id"] == created["id"]
        assert read["legal_name"] == DESIGNEE_NAME
        assert read["us_address_line"] == DESIGNEE_ADDRESS
        assert read["contact_phone"] == DESIGNEE_PHONE
        assert read["contact_email"] == DESIGNEE_EMAIL
        assert read["designation_cap"] == DECLARED_CAP

    def test_a_designee_holding_nothing_reads_dormant_at_zero_units_of_capacity_used(self, api):
        """The two derived fields on the read are the designation status and its live count, and
        a party that has never been designated reads the floor of both. An omitted ceiling reads
        back as the declared default rather than as null.

        PRD: "A new responsible person starts with `active_designation_count` at 0 and `status` `DORMANT`."
        PRD: "When `designation_cap` is omitted it defaults to 25, and it may be set anywhere from 1 to 500."

        Design: Corner/endpoints/responsible_person_create_then_read_round_trips_every_stored_field
        """
        declared = _create_designee(api, designation_cap=DECLARED_CAP)
        defaulted = _create_designee(api)

        declared_read = X.read_responsible_person(api, declared["id"])
        defaulted_read = X.read_responsible_person(api, defaulted["id"])

        assert declared_read["status"] == K.RP_STATUS_DORMANT
        assert declared_read["active_designation_count"] == 0
        assert declared_read["designation_cap"] == DECLARED_CAP
        assert defaulted_read["status"] == K.RP_STATUS_DORMANT
        assert defaulted_read["active_designation_count"] == 0
        assert defaulted_read["designation_cap"] == DEFAULT_CAP

    def test_neither_reader_bumps_the_version_of_what_it_read(self, api):
        """A read is not a mutation, so two successive reads — one by the agency, one by the
        owning agent — leave the version exactly where creation left it.

        PRD: "`version` is an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation, cascaded mutations included."

        Design: Corner/endpoints/responsible_person_create_then_read_round_trips_every_stored_field
        """
        created = _create_designee(api, designation_cap=DECLARED_CAP)
        assert created["version"] == 1
        assert created["created_at"] == created["updated_at"]

        agency_read = get_success_data(
            api.get_responsible_person(created["id"], REVIEWER_HEADERS)
        )
        owner_read = get_success_data(
            api.get_responsible_person(
                created["id"], make_responsible_person_agent_headers(created["id"])
            )
        )

        assert agency_read["version"] == 1
        assert owner_read["version"] == 1
        assert owner_read["updated_at"] == created["updated_at"]


def _open_withdrawal_over_three_shipments(api):
    """A listed product with three non-touching shipments of one lot and an OPEN round.

    The three windows are kept apart because same-lot windows may not overlap or
    even touch, so the aggregate of the lot is built from disjoint days.
    """
    bundle = X.listed_bundle(
        api,
        listing_overrides={"product_name": "Aster Blush Powder", "lot_authorized_units": 5000},
        person_overrides={"legal_name": DESIGNEE_NAME},
    )
    records = X.create_distribution_records(api, bundle["listing_id"], bundle["agent"], [
        {"lot_code": LOT_E, "consignee_name": "Gulf Coast Retail Group",
         "consignee_class": K.DEPTH_RETAIL, "ship_date": "2026-08-05",
         "delivery_date": "2026-08-06", "units_shipped": RETAIL_UNITS},
        {"lot_code": LOT_E, "consignee_name": "Northway Wholesale",
         "consignee_class": K.DEPTH_WHOLESALE, "ship_date": "2026-08-08",
         "delivery_date": "2026-08-09", "units_shipped": WHOLESALE_UNITS},
        {"lot_code": LOT_E, "consignee_name": "Harbor Drug Mart",
         "consignee_class": K.DEPTH_RETAIL, "ship_date": "2026-08-11",
         "delivery_date": "2026-08-12", "units_shipped": DRUG_MART_UNITS},
    ])
    recall = X.recall_with_accepted_plan(
        api, bundle["listing_id"], bundle["agent"],
        K.INITIATION_BASIS_MANDATORY, officer=OFFICER_HEADERS,
    )
    withdrawal = X.open_withdrawal(api, recall, OFFICER_HEADERS, scope_depth=K.DEPTH_CONSUMER)
    bundle.update({
        "records": records,
        "record_ids": [record["id"] for record in records],
        "recall": recall,
        "withdrawal": withdrawal,
        "withdrawal_id": withdrawal["id"],
    })
    return bundle


def _linked_records(api, withdrawal_id):
    """Every distribution record the register reports as linked to this round."""
    rows, meta = validate_paginated(
        api.list_distribution_records(
            OFFICER_HEADERS, {"withdrawal_id": withdrawal_id, "limit": K.MAX_LIMIT}
        )
    )
    return rows, meta


class TestABatchOfProducedRecordsIsAllOrNothing:
    """One unresolvable identifier in the list voids the entire production."""

    def test_the_unknown_third_identifier_refuses_the_whole_batch(self, api):
        """Two of the three named records exist; the third does not, and the batch is reported
        against that first unresolvable identifier rather than partially honoured.

        PRD: "Every identifier in the list must resolve to a record — validated in payload order, so the first unresolvable identifier is the one reported as `ERR_DISTRIBUTION_RECORD_NOT_FOUND` (HTTP 404) — the list must name at least one record, or it is refused with `ERR_NO_DISTRIBUTION_RECORDS` (HTTP 422), and every named record must belong to the listing the recall was opened against, or it is refused with `ERR_DISTRIBUTION_RECORD_LISTING_MISMATCH` (HTTP 422)."

        Design: Corner/endpoints/records_production_is_atomic_across_three_records
        """
        bundle = _open_withdrawal_over_three_shipments(api)
        first, second, _third = bundle["record_ids"]

        validate_error(
            api.produce_records(
                bundle["withdrawal_id"],
                F.records_production_payload([first, second, NON_EXISTENT_UUID]),
                bundle["agent"],
            ),
            E.ERR_DISTRIBUTION_RECORD_NOT_FOUND,
        )

        withdrawal = X.read_withdrawal(api, bundle["withdrawal_id"])
        assert withdrawal["status"] == K.WITHDRAWAL_STATUS_OPEN
        assert withdrawal["records_produced_count"] == 0
        assert withdrawal["shipped_units_total"] == 0
        assert withdrawal["outstanding_units_total"] == 0

    def test_the_two_valid_identifiers_were_not_partially_linked(self, api):
        """Linkage is the whole of what production does, so a refused production leaves every
        named record exactly as the shipment created it — unlinked and wholly outstanding.

        PRD: "Production sets each named record's `withdrawal_id` to this withdrawal, sets `records_produced_count` to the number of linked records and `shipped_units_total` to the sum of their `units_shipped`, sets `outstanding_units_total` equal to `shipped_units_total` because nothing has been verified yet, leaves both recovery rates at 0.00, and takes `OPEN → RECORDS_PRODUCED`."
        PRD: "A new record is created with `withdrawal_id` null, all five recovery buckets at 0 and `units_outstanding` equal to `units_shipped`, and the listing's `distributed_units_total` rises by the units shipped."

        Design: Corner/endpoints/records_production_is_atomic_across_three_records
        """
        bundle = _open_withdrawal_over_three_shipments(api)
        first, second, _third = bundle["record_ids"]
        validate_error(
            api.produce_records(
                bundle["withdrawal_id"],
                F.records_production_payload([first, second, NON_EXISTENT_UUID]),
                bundle["agent"],
            ),
            E.ERR_DISTRIBUTION_RECORD_NOT_FOUND,
        )

        rows, meta = _linked_records(api, bundle["withdrawal_id"])
        assert rows == []
        assert meta["total_count"] == 0
        for record_id in bundle["record_ids"]:
            record = X.read_record(api, record_id)
            assert record["withdrawal_id"] is None
            assert record["units_outstanding"] == record["units_shipped"]
            A.assert_record_unit_balance(record)

    def test_the_corrected_batch_links_all_three_shipments_in_one_call(self, api):
        """With every identifier resolvable the production is a single act: three links, the
        summed denominator and the state move, all in one call.

        PRD: "Production sets each named record's `withdrawal_id` to this withdrawal, sets `records_produced_count` to the number of linked records and `shipped_units_total` to the sum of their `units_shipped`, sets `outstanding_units_total` equal to `shipped_units_total` because nothing has been verified yet, leaves both recovery rates at 0.00, and takes `OPEN → RECORDS_PRODUCED`."

        Design: Corner/endpoints/records_production_is_atomic_across_three_records
        """
        bundle = _open_withdrawal_over_three_shipments(api)
        validate_error(
            api.produce_records(
                bundle["withdrawal_id"],
                F.records_production_payload(
                    [bundle["record_ids"][0], bundle["record_ids"][1], NON_EXISTENT_UUID]
                ),
                bundle["agent"],
            ),
            E.ERR_DISTRIBUTION_RECORD_NOT_FOUND,
        )

        produced = X.produce_records(
            api, bundle["withdrawal_id"], bundle["record_ids"], bundle["agent"]
        )

        assert produced["status"] == K.WITHDRAWAL_STATUS_RECORDS_PRODUCED
        assert produced["records_produced_count"] == 3
        assert produced["shipped_units_total"] == ALL_THREE_UNITS
        assert produced["outstanding_units_total"] == ALL_THREE_UNITS
        A.assert_two_decimal_value(produced["reported_recovery_rate"], 0.00, "reported rate")
        A.assert_two_decimal_value(produced["verified_recovery_rate"], 0.00, "verified rate")

        rows, meta = _linked_records(api, bundle["withdrawal_id"])
        assert meta["total_count"] == 3
        assert sorted(A.ids_of(rows)) == sorted(bundle["record_ids"])
        assert [row["withdrawal_id"] for row in rows] == [bundle["withdrawal_id"]] * 3


class TestTheOpsClockReportsTheInstantItReplaced:
    """The operator capability answers with both ends of the move it performed."""

    def test_the_first_move_answers_with_the_startup_default_it_displaced(self, api):
        """Setting the clock to the value it already holds still reports both ends of the move,
        and the displaced instant is the mandatory startup default.

        PRD: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`."
        PRD: "A `SystemOperator` may move the clock to any UTC instant by supplying `current_utc`; the call answers with the new `current_utc` and the `previous_utc` it displaced, and performs no state transitions of its own."

        Design: Corner/endpoints/clock_endpoint_reports_the_instant_it_replaced
        """
        first = get_success_data(api.set_clock(SEED_INSTANT, OPERATOR_HEADERS))

        assert first["current_utc"] == SEED_INSTANT
        assert first["previous_utc"] == SEED_INSTANT

        rows, meta = validate_paginated(api.list_facilities(REVIEWER_HEADERS, {"limit": 100}))
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_second_move_displaces_the_first_value_not_the_seed(self, api):
        """Chained moves report what the immediately preceding call left behind, so the second
        call's displaced instant is the first call's value.

        PRD: "A `SystemOperator` may move the clock to any UTC instant by supplying `current_utc`; the call answers with the new `current_utc` and the `previous_utc` it displaced, and performs no state transitions of its own."

        Design: Corner/endpoints/clock_endpoint_reports_the_instant_it_replaced
        """
        get_success_data(api.set_clock(SEED_INSTANT, OPERATOR_HEADERS))

        second = get_success_data(api.set_clock(LATER_INSTANT, OPERATOR_HEADERS))

        assert second["current_utc"] == LATER_INSTANT
        assert second["previous_utc"] == SEED_INSTANT

    def test_the_domain_then_reads_the_moved_clock(self, api):
        """The move is not merely reported: an intake instant that would have been future-dated
        against the seed is accepted once the clock has been carried past it.

        PRD: "One business condition applies: `received_at` must not be after the logical clock, since nobody can have received a report from the future; a later instant is refused with `ERR_RECEIVED_AT_IN_FUTURE` (HTTP 422)."

        Design: Corner/endpoints/clock_endpoint_reports_the_instant_it_replaced
        """
        bundle = X.registered_facility_with_listing(api)
        get_success_data(api.set_clock(SEED_INSTANT, OPERATOR_HEADERS))
        moved = get_success_data(api.set_clock(LATER_INSTANT, OPERATOR_HEADERS))
        assert moved["current_utc"] == LATER_INSTANT

        event = X.record_serious_event(
            api, bundle["listing_id"], bundle["agent"], received_at=LATER_INSTANT
        )

        assert event["received_at"] == LATER_INSTANT
        assert event["report_status"] == K.EVENT_STATUS_REPORT_DUE


class TestTheSweepOnAQuietDatabaseIsAPureNoOp:
    """Nothing is due, so the checkpoint observes the clock and changes nothing."""

    def _quiet_establishment(self, api):
        """An approved establishment with one DRAFT listing and nothing overdue."""
        X.set_clock(api, SEED_INSTANT)
        return X.registered_facility_with_listing(
            api,
            listing_overrides={"product_name": "Aster Blush Powder"},
            person_overrides={"legal_name": DESIGNEE_NAME},
        )

    def test_all_seven_counters_report_zero_against_the_logical_clock(self, api):
        """The whole output of a sweep with nothing to do is seven zeros and the instant it read,
        which is the logical clock rather than wall time.

        PRD: "The sweep is a `SystemOperator` checkpoint that takes no payload and executes three steps against the logical clock, always in the same order, and its whole output is a set of counters plus the `swept_at` instant at which it ran — the logical-clock value it read."

        Design: Corner/endpoints/compliance_sweep_on_a_quiet_database_returns_all_seven_zero_counts
        """
        self._quiet_establishment(api)

        result = X.run_sweep(api)

        A.assert_sweep_counters(result)
        assert result["swept_at"] == SEED_INSTANT

    def test_the_repeat_call_at_the_same_clock_repeats_the_all_zero_report(self, api):
        """Running the checkpoint again without moving the clock is safe: the second response is
        another all-zero report against the same instant, not an error and not a re-processing.

        PRD: "Running it twice without moving the logical clock in between yields a second response whose every counter is zero and whose `swept_at` equals the clock, because each of the three steps selects only records whose state still admits the transition, and the first run has already moved them all."

        Design: Corner/endpoints/compliance_sweep_on_a_quiet_database_returns_all_seven_zero_counts
        """
        self._quiet_establishment(api)
        first = X.run_sweep(api)

        second = X.run_sweep(api)

        A.assert_sweep_counters(first)
        A.assert_sweep_counters(second)
        assert first["swept_at"] == SEED_INSTANT
        assert second["swept_at"] == SEED_INSTANT

    def test_neither_sweep_moved_the_establishment_the_listing_or_the_ledger(self, api):
        """The renewal window has not opened and coverage has not run out, so step 1 selects
        nothing; the observation leaves both records and the append-only ledger untouched.

        PRD: "An establishment whose `registration_status` is `REGISTERED` and whose `renewal_window_open_date` has arrived is moved to `RENEWAL_DUE`, and each such move is counted in `renewal_due_facility_count`."
        PRD: "That property is what makes the sweep safe to run as often as an operator likes: it is an observation of the clock, not an increment of anything."

        Design: Corner/endpoints/compliance_sweep_on_a_quiet_database_returns_all_seven_zero_counts
        """
        bundle = self._quiet_establishment(api)
        before_rows, _before_meta = X.read_ledger(api, bundle["facility_id"])

        X.run_sweep(api)
        X.run_sweep(api)

        facility = X.read_facility(api, bundle["facility_id"])
        assert facility["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
        assert facility["compliance_posture"] == K.POSTURE_OPEN
        assert facility["renewal_window_open_date"] == K.CANONICAL_RENEWAL_WINDOW_OPEN_DATE
        assert X.read_listing(api, bundle["listing_id"])["listing_status"] == \
            K.LISTING_STATUS_DRAFT

        after_rows, _after_meta = X.read_ledger(api, bundle["facility_id"])
        assert len(after_rows) == len(before_rows)
        assert A.ids_of(after_rows) == A.ids_of(before_rows)


CITRAL_PCT = 0.0020
GERANIOL_PCT = 0.0050


class TestTheListingReadTracksEveryIngredientWrite:
    """The derived disclosure projection is recomputed, never served stale."""

    def test_a_listing_with_no_ingredients_reads_complete_yet_unmarketable(self, api):
        """A vacuous required set resolves to complete, and completeness is only one of the four
        conditions a marketable product must satisfy.

        PRD: "A freshly created listing answers 201 and begins with `listing_status` `DRAFT`, `safety_status` `UNSUBSTANTIATED`, `listing_number` and `suspension_reason` both null, `allergen_disclosure_complete` true, `undisclosed_allergen_count` 0, `distributed_units_total` 0, `open_recall_count` 0, `open_serious_event_count` 0, `marketable` false and `version` 1."
        PRD: "The vacuous case must resolve to complete, not incomplete: a listing with no ingredients at all, a listing whose fragrance allergens all sit below the threshold, and a professional-use-only listing all report `undisclosed_allergen_count` 0 and `allergen_disclosure_complete` true."

        Design: Corner/endpoints/listing_read_recomputes_its_derived_disclosure_fields_after_each_ingredient_write
        """
        bundle = X.registered_facility_with_listing(
            api,
            listing_overrides={"product_name": "Aster Blush Powder",
                               "product_form": K.PRODUCT_FORM_LEAVE_ON},
            person_overrides={"legal_name": DESIGNEE_NAME},
        )

        listing = X.read_listing(api, bundle["listing_id"])

        assert listing["undisclosed_allergen_count"] == 0
        assert listing["allergen_disclosure_complete"] is True
        assert listing["marketable"] is False

    def test_one_undisclosed_leave_on_allergen_flips_the_projection(self, api):
        """The write recomputes the read: a single undisclosed allergen at 0.0020 percent sits at
        or above the leave-on threshold, so the count rises and completeness fails.

        PRD: "For each ingredient of the listing, `disclosure_required` is true when all three of the following hold: `is_fragrance_allergen` is true, `concentration_pct` is at or above the applicable threshold — the comparison is inclusive, and it is made against the stored four-decimal value — and the listing's `professional_use_only` is false."
        PRD: "It computes that row's `disclosure_required`, recomputes the listing's `undisclosed_allergen_count`, `allergen_disclosure_complete` and `marketable`, and refreshes `data_gap_present` on every substantiation dossier of the listing that is not yet `SUPERSEDED` — so an ingredient carrying `is_data_gap_flag` can retroactively change how an already-open dossier must be reviewed."

        Design: Corner/endpoints/listing_read_recomputes_its_derived_disclosure_fields_after_each_ingredient_write
        """
        bundle = X.registered_facility_with_listing(
            api,
            listing_overrides={"product_name": "Aster Blush Powder",
                               "product_form": K.PRODUCT_FORM_LEAVE_ON},
            person_overrides={"legal_name": DESIGNEE_NAME},
        )
        before = X.read_listing(api, bundle["listing_id"])
        assert before["undisclosed_allergen_count"] == 0

        citral = X.add_ingredient(
            api, bundle["listing_id"], bundle["agent"],
            F.allergen_ingredient_payload(
                inci_name="CITRAL", concentration_pct=CITRAL_PCT, label_disclosed=False
            ),
        )

        assert citral["disclosure_required"] is True
        after = X.read_listing(api, bundle["listing_id"])
        assert after["undisclosed_allergen_count"] == 1
        assert after["allergen_disclosure_complete"] is False
        assert after["marketable"] is False

    def test_a_disclosed_allergen_above_the_threshold_never_inflates_the_count(self, api):
        """The second allergen is above the threshold too, so its disclosure duty is real — but
        it is named on the label, so it satisfies that duty and the gap count stays at one.

        PRD: "From those flags, `undisclosed_allergen_count` is the number of ingredients whose `disclosure_required` is true while `label_disclosed` is false, and `allergen_disclosure_complete` is true exactly when that count is 0."
        PRD: "The listing's ingredients are read back in ascending `created_at` order, optionally narrowed by an `is_fragrance_allergen` filter, and each row carries its computed `disclosure_required`."

        Design: Corner/endpoints/listing_read_recomputes_its_derived_disclosure_fields_after_each_ingredient_write
        """
        bundle = X.registered_facility_with_listing(
            api,
            listing_overrides={"product_name": "Aster Blush Powder",
                               "product_form": K.PRODUCT_FORM_LEAVE_ON},
            person_overrides={"legal_name": DESIGNEE_NAME},
        )
        X.add_ingredient(
            api, bundle["listing_id"], bundle["agent"],
            F.allergen_ingredient_payload(
                inci_name="CITRAL", concentration_pct=CITRAL_PCT, label_disclosed=False
            ),
        )

        geraniol = X.add_ingredient(
            api, bundle["listing_id"], bundle["agent"],
            F.allergen_ingredient_payload(
                inci_name="GERANIOL", concentration_pct=GERANIOL_PCT, label_disclosed=True
            ),
        )

        assert geraniol["disclosure_required"] is True
        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["undisclosed_allergen_count"] == 1
        assert listing["allergen_disclosure_complete"] is False
        assert listing["marketable"] is False

        rows, meta = validate_paginated(
            api.list_ingredients(
                bundle["listing_id"], REVIEWER_HEADERS,
                {"is_fragrance_allergen": True, "limit": K.MAX_LIMIT},
            )
        )
        assert meta["total_count"] == 2
        assert [row["inci_name"] for row in rows] == ["CITRAL", "GERANIOL"]
        assert [row["disclosure_required"] for row in rows] == [True, True]
        assert [row["label_disclosed"] for row in rows] == [False, True]
