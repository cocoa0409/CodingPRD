"""Use evidence, segregation of collection/verification, the verified-evidence
count ledger, and maintenance filings: windows, fees, evidence integrity, and
the acceptance/cancellation cycles."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    collect_evidence,
    create_maintenance_filing,
    create_record,
    get_maintenance_filing,
    get_record,
    make_associate_headers,
    make_paralegal_headers,
    make_partner_headers,
    publish_record,
    register_record,
    set_clock,
    setup_published_record,
    setup_record_with_verified_evidence,
    setup_registered_record,
    validate_error,
    validate_success,
    verify_evidence,
)


class TestEvidenceBasics:
    def test_evidence_item_creation_defaults(self, api, paralegal_headers):
        """PRD §3.9: "The item starts `COLLECTED` with `collected_by_user_id`
        stamped and `verified_by_user_id` null."

        Design: Corner/entities/evidence_item_creation_defaults
        """
        _, record = setup_published_record(classes=(9,))
        res = api.collect_evidence(
            record["id"],
            {"nice_class": 9, "specimen_type": "LABEL",
             "specimen_date": "2026-06-01T00:00:00Z"},
            paralegal_headers,
        )
        item = validate_success(res, 201)
        assert item["status"] == "COLLECTED"
        assert item["verified_by_user_id"] is None
        assert item["collected_by_user_id"] == "para_1"
        assert isinstance(item["version"], int)

    def test_associate_cannot_verify_own_collected_evidence(self, api):
        """PRD §3.9: "Verification, by an `AssociateAttorney` or `PartnerAttorney`
        other than the collector, moves the item to `VERIFIED`, stamps
        `verified_by_user_id`, and recomputes the record's
        `verified_evidence_count`; a self-verify draws `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.1: "the caller verifying an evidence item must differ from its
        `collected_by_user_id`"

        Design: Corner/validations/associate_cannot_verify_own_collected_evidence
        """
        _, record = setup_published_record(classes=(9,))
        item = collect_evidence(record["id"], nice_class=9,
                                specimen_date="2026-06-01T00:00:00Z",
                                user_id="assoc_1", role="AssociateAttorney")

        res = api.verify_evidence(item["id"], make_associate_headers("assoc_1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        verified = validate_success(
            api.verify_evidence(item["id"], make_partner_headers("partner_1")), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "partner_1"

    def test_evidence_class_not_on_record_rejected(self, api, paralegal_headers):
        """PRD §3.9: "A `Paralegal` or `AssociateAttorney` collects a specimen
        against a record, naming the `nice_class` it supports — which must be one of
        the record's own `nice_classes`, else `ERR_CLASS_NOT_ON_RECORD`"

        Design: Corner/validations/evidence_class_not_on_record_rejected
        """
        _, record = setup_published_record(classes=(9, 25))
        res = api.collect_evidence(
            record["id"],
            {"nice_class": 10, "specimen_type": "LABEL",
             "specimen_date": "2031-06-01T00:00:00Z"},
            paralegal_headers,
        )
        validate_error(res, ApiErrorId.ERR_CLASS_NOT_ON_RECORD, expected_status=422)

    def test_evidence_count_reconciliation_forward_and_reverse(
        self, api, paralegal_headers
    ):
        """PRD §3.9: "Verification, by an `AssociateAttorney` or `PartnerAttorney`
        other than the collector, moves the item to `VERIFIED`, stamps
        `verified_by_user_id`, and recomputes the record's
        `verified_evidence_count`; a self-verify draws `ERR_SEGREGATION_OF_DUTIES`.
        Rejection, with a `reason`, moves an item from `COLLECTED` or `VERIFIED` to
        its terminal `REJECTED` state and recomputes the count — a rejection from
        `VERIFIED` is the compensating action that decrements it."

        Design: Corner/complexity_layers/evidence_count_reconciliation_forward_and_reverse
        """
        _, record = setup_published_record(classes=(9,))
        assert get_record(record["id"])["verified_evidence_count"] == 0

        item = collect_evidence(record["id"], nice_class=9,
                                specimen_date="2026-06-01T00:00:00Z", user_id="para_1")
        verify_evidence(item["id"], user_id="assoc_1")
        assert get_record(record["id"])["verified_evidence_count"] == 1

        validate_success(
            api.reject_evidence(item["id"], {"reason": "specimen illegible"},
                                make_associate_headers("assoc_1")), 200)
        assert get_record(record["id"])["verified_evidence_count"] == 0


class TestMaintenanceRecordGate:
    def test_submit_rejected_while_record_not_registered(self, api,
                                                         paralegal_headers):
        """PRD §3.9: "The record must be `REGISTERED` or `MAINTENANCE_DUE`
        (`ERR_RECORD_NOT_REGISTERED`)."

        Design: Difficulty/cross_entity_state_dependency/maintenance_submit_requires_registered_record
        """
        _, record = setup_published_record(classes=(9,))
        item = collect_evidence(record["id"], nice_class=9,
                                specimen_date="2031-06-01T00:00:00Z", user_id="para_1")
        verify_evidence(item["id"], user_id="assoc_1")
        filing = create_maintenance_filing(record["id"], [item["id"]])
        set_clock("2031-09-01T00:00:00Z")

        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_RECORD_NOT_REGISTERED, expected_status=409)
        assert get_maintenance_filing(filing["id"])["status"] == "PREPARED"

    def test_submit_succeeds_once_record_registered(self, api, paralegal_headers):
        """PRD §3.9: "The record must be `REGISTERED` or `MAINTENANCE_DUE`
        (`ERR_RECORD_NOT_REGISTERED`). Submission within the closed interval from
        `maintenance_window_open` through `maintenance_window_close` inclusive lands
        the filing in `SUBMITTED`"
        PRD §3.2: "Registration, also by a `Paralegal`, carries the
        `registration_date` and moves the record from `PUBLISHED` to `REGISTERED`,
        computing the three maintenance horizons: `maintenance_window_open` five
        years after registration, `maintenance_window_close` six years after
        registration, and `maintenance_grace_close` six months beyond the window
        close."

        Design: Difficulty/cross_entity_state_dependency/maintenance_submit_requires_registered_record
        """
        _, record = setup_published_record(classes=(9,))
        item = collect_evidence(record["id"], nice_class=9,
                                specimen_date="2031-06-01T00:00:00Z", user_id="para_1")
        verify_evidence(item["id"], user_id="assoc_1")
        filing = create_maintenance_filing(record["id"], [item["id"]])

        register_record(record["id"], "2026-08-10T00:00:00Z")
        record_after = get_record(record["id"])
        assert_instant_equal(record_after["maintenance_window_open"],
                             "2031-08-10T00:00:00Z", "maintenance_window_open")
        assert_instant_equal(record_after["maintenance_window_close"],
                             "2032-08-10T00:00:00Z", "maintenance_window_close")
        set_clock("2031-09-01T00:00:00Z")

        submitted = validate_success(
            api.submit_maintenance_filing(filing["id"], paralegal_headers), 200)
        assert submitted["status"] == "SUBMITTED"


class TestSubmitPriorityPair:
    def test_state_beats_temporal_on_maintenance_resubmit(self, api,
                                                          paralegal_headers):
        """PRD §2.10: "Every request is validated against an ordered pipeline; an
        earlier failure masks later ones, so callers always see the highest-priority
        applicable error."
        PRD §2.10: "5. **State** — the target entity is in a state from which the
        requested transition is declared, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."
        PRD §2.10: "9.–11. **Temporal rules**, in order: the opposition window
        (`ERR_OPPOSITION_WINDOW_CLOSED`), the maintenance filing window
        (`ERR_OUTSIDE_FILING_WINDOW`), and the litigation-escalation response window
        (`ERR_RESPONSE_WINDOW_OPEN`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_maintenance_resubmit
        """
        _, record, evidence_ids = setup_record_with_verified_evidence(classes=(9,))
        filing = create_maintenance_filing(record["id"], evidence_ids)
        set_clock("2031-09-01T00:00:00Z")
        validate_success(api.submit_maintenance_filing(filing["id"],
                                                       paralegal_headers), 200)
        set_clock("2033-03-01T00:00:00Z")
        # Both violations present: filing already SUBMITTED (state, priority 5) and
        # the clock 2033-03-01 is past the grace close 2033-02-10 (temporal,
        # priority 10). The earlier state failure masks the temporal one.
        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_maintenance_filing(filing["id"])["status"] == "SUBMITTED"

    def test_resubmit_in_window_also_surfaces_invalid_state(self, api,
                                                            paralegal_headers):
        """PRD §2.10: "5. **State** — the target entity is in a state from which the
        requested transition is declared, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."
        PRD §3.9: "Rejection lands the filing in `REJECTED_OFFICE`, from which a
        fresh submission re-evaluates the window and may land timely or late."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_maintenance_resubmit
        """
        _, record, evidence_ids = setup_record_with_verified_evidence(classes=(9,))
        filing = create_maintenance_filing(record["id"], evidence_ids)
        set_clock("2031-09-01T00:00:00Z")
        validate_success(api.submit_maintenance_filing(filing["id"],
                                                       paralegal_headers), 200)
        # Same filing re-submitted while still inside the window: isolated state
        # violation (submit is declared only from PREPARED/REJECTED_OFFICE).
        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_maintenance_filing(filing["id"])["status"] == "SUBMITTED"


class TestMaintenanceFees:
    def test_fee_band_standard_below_240000_base(self, api, paralegal_headers):
        """PRD §3.9: "First the base: the record's class count times 40000 cents per
        class, stored on `fee_base_cents`. Second the band, read from the base only —
        never from the total: a base of at least 240000 cents is the `HIGH` band,
        otherwise `STANDARD`. Third the surcharge: the base times one quarter for
        `HIGH` or one tenth for `STANDARD`, rounded half-up to whole cents, stored on
        `fee_surcharge_cents`."
        PRD §3.9: "A `Paralegal` prepares a maintenance filing on a record, choosing
        a `filing_type` of `SECTION_8` or `RENEWAL` and listing the
        `evidence_item_ids` relied on; the filing starts `PREPARED` with its fees
        computed."

        Design: Difficulty/combinatorial_formula/maintenance_fee_band_pinned_to_base_not_total
        """
        _, record = setup_registered_record(classes=(1, 2, 3, 4, 5))
        res = api.create_maintenance_filing(
            record["id"], {"filing_type": "SECTION_8", "evidence_item_ids": []},
            make_paralegal_headers("para_1"))
        filing = validate_success(res, 201)
        assert filing["status"] == "PREPARED"
        # 5 classes x 40000 = 200000 base < 240000 -> STANDARD band, 10% surcharge.
        assert filing["fee_base_cents"] == 200000
        assert filing["fee_surcharge_cents"] == 20000
        assert filing["late_fee_cents"] == 0
        assert filing["fee_total_cents"] == 220000

    def test_fee_band_high_at_exactly_240000_base(self, api, paralegal_headers):
        """PRD §3.9: "Second the band, read from the base only — never from the
        total: a base of at least 240000 cents is the `HIGH` band, otherwise
        `STANDARD`. Third the surcharge: the base times one quarter for `HIGH` or one
        tenth for `STANDARD`, rounded half-up to whole cents, stored on
        `fee_surcharge_cents`."

        Design: Difficulty/combinatorial_formula/maintenance_fee_band_pinned_to_base_not_total
        """
        _, record = setup_registered_record(classes=(1, 2, 3, 4, 5, 6))
        res = api.create_maintenance_filing(
            record["id"], {"filing_type": "SECTION_8", "evidence_item_ids": []},
            make_paralegal_headers("para_1"))
        filing = validate_success(res, 201)
        # 6 classes x 40000 = 240000 base, exactly at the HIGH-band minimum
        # (inclusive) -> 25% surcharge 60000, total 300000.
        assert filing["fee_base_cents"] == 240000
        assert filing["fee_surcharge_cents"] == 60000
        assert filing["late_fee_cents"] == 0
        assert filing["fee_total_cents"] == 300000

    def test_maintenance_late_fee_in_grace_window(self, api, paralegal_headers):
        """PRD §3.9: "submission after the window close but at or before
        `maintenance_grace_close` lands it in `LATE_FILED`"
        PRD §3.9: "Fourth the late fee: the class count times 10000 cents when the
        filing lands in the grace window, else zero, stored on `late_fee_cents`.
        Fifth the total, `fee_total_cents`, is the sum of the three components, and
        `is_late` records whether the grace window applied."

        Design: Corner/calculations/maintenance_late_fee_in_grace_window
        """
        _, record, evidence_ids = setup_record_with_verified_evidence(
            classes=(9, 25), specimen_date="2031-06-01T00:00:00Z")
        filing = create_maintenance_filing(record["id"], evidence_ids)
        # Window: open 2031-08-10, close 2032-08-10, grace close 2033-02-10.
        set_clock("2032-09-01T00:00:00Z")

        submitted = validate_success(
            api.submit_maintenance_filing(filing["id"], paralegal_headers), 200)
        assert submitted["status"] == "LATE_FILED"
        assert submitted["is_late"] is True
        assert submitted["fee_base_cents"] == 80000
        assert submitted["fee_surcharge_cents"] == 8000
        assert submitted["late_fee_cents"] == 20000
        assert submitted["fee_total_cents"] == 108000


class TestMaintenanceEvidenceIntegrity:
    def test_filing_referencing_other_record_evidence_rejected(
        self, api, paralegal_headers
    ):
        """PRD §3.9: "Every listed evidence item must belong to this record
        (`ERR_EVIDENCE_RECORD_MISMATCH`)"

        Design: Corner/validations/filing_referencing_other_record_evidence_rejected
        """
        client, record_a = setup_registered_record(classes=(9,), registration_date="2026-08-10T00:00:00Z")
        record_b = create_record(client["id"], mark_text="BETA", classes=(9,),
                                 app_no="US-B1")
        item_b = collect_evidence(record_b["id"], nice_class=9,
                                  specimen_date="2031-06-01T00:00:00Z",
                                  user_id="para_1")
        verify_evidence(item_b["id"], user_id="assoc_1")
        filing = create_maintenance_filing(record_a["id"], [item_b["id"]])
        set_clock("2031-09-01T00:00:00Z")

        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_EVIDENCE_RECORD_MISMATCH,
                       expected_status=422)
        assert get_maintenance_filing(filing["id"])["status"] == "PREPARED"

    def test_filing_with_unverified_evidence_rejected(self, api, paralegal_headers):
        """PRD §3.9: "Every listed evidence item must belong to this record
        (`ERR_EVIDENCE_RECORD_MISMATCH`), be `VERIFIED`
        (`ERR_EVIDENCE_NOT_VERIFIED`)"

        Design: Corner/validations/filing_with_unverified_evidence_rejected
        """
        _, record = setup_registered_record(classes=(9,))
        item = collect_evidence(record["id"], nice_class=9,
                                specimen_date="2031-06-01T00:00:00Z", user_id="para_1")
        filing = create_maintenance_filing(record["id"], [item["id"]])
        set_clock("2031-09-01T00:00:00Z")

        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_EVIDENCE_NOT_VERIFIED, expected_status=422)
        assert get_maintenance_filing(filing["id"])["status"] == "PREPARED"

    def test_filing_with_stale_evidence_rejected(self, api, paralegal_headers):
        """PRD §3.9: "Every listed evidence item must belong to this record
        (`ERR_EVIDENCE_RECORD_MISMATCH`), be `VERIFIED`
        (`ERR_EVIDENCE_NOT_VERIFIED`), and bear a `specimen_date` no earlier than 36
        months before `maintenance_window_close` (`ERR_EVIDENCE_STALE`)"

        Design: Corner/validations/filing_with_stale_evidence_rejected
        """
        _, record = setup_registered_record(classes=(9, 25))
        # window_close 2032-08-10; staleness cutoff = 2029-08-10.
        stale = collect_evidence(record["id"], nice_class=9,
                                 specimen_date="2029-08-09T00:00:00Z",
                                 user_id="para_1")
        verify_evidence(stale["id"], user_id="assoc_1")
        fresh = collect_evidence(record["id"], nice_class=25,
                                 specimen_type="PACKAGING",
                                 specimen_date="2029-08-10T00:00:00Z",
                                 user_id="para_1")
        verify_evidence(fresh["id"], user_id="assoc_1")
        filing = create_maintenance_filing(record["id"], [stale["id"], fresh["id"]])
        set_clock("2031-09-01T00:00:00Z")

        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_EVIDENCE_STALE, expected_status=422)
        assert get_maintenance_filing(filing["id"])["status"] == "PREPARED"

    def test_specimen_exactly_at_staleness_cutoff_is_fresh(self, api,
                                                           paralegal_headers):
        """PRD §3.9: "and bear a `specimen_date` no earlier than 36 months before
        `maintenance_window_close` (`ERR_EVIDENCE_STALE`)"
        PRD §3.9: "Submission within the closed interval from
        `maintenance_window_open` through `maintenance_window_close` inclusive lands
        the filing in `SUBMITTED`"

        Design: Corner/validations/filing_with_stale_evidence_rejected
        """
        _, record = setup_registered_record(classes=(25,))
        # window_close 2032-08-10; specimen exactly at the 2029-08-10 cutoff.
        item = collect_evidence(record["id"], nice_class=25,
                                specimen_type="PACKAGING",
                                specimen_date="2029-08-10T00:00:00Z",
                                user_id="para_1")
        verify_evidence(item["id"], user_id="assoc_1")
        filing = create_maintenance_filing(record["id"], [item["id"]])
        set_clock("2031-09-01T00:00:00Z")

        submitted = validate_success(
            api.submit_maintenance_filing(filing["id"], paralegal_headers), 200)
        assert submitted["status"] == "SUBMITTED"

    def test_filing_incomplete_class_coverage_rejected(self, api, paralegal_headers):
        """PRD §3.9: "and every Nice class of the record must be covered by at least
        one listed verified item (`ERR_INCOMPLETE_CLASS_COVERAGE`)."

        Design: Corner/validations/filing_incomplete_class_coverage_rejected
        """
        _, record = setup_registered_record(classes=(9, 25))
        item = collect_evidence(record["id"], nice_class=9,
                                specimen_date="2031-06-01T00:00:00Z", user_id="para_1")
        verify_evidence(item["id"], user_id="assoc_1")
        filing = create_maintenance_filing(record["id"], [item["id"]])
        set_clock("2031-09-01T00:00:00Z")

        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_INCOMPLETE_CLASS_COVERAGE,
                       expected_status=422)
        assert get_maintenance_filing(filing["id"])["status"] == "PREPARED"

    def test_submit_before_window_open_returns_outside_filing_window(
        self, api, paralegal_headers
    ):
        """PRD §3.9: "Submission within the closed interval from
        `maintenance_window_open` through `maintenance_window_close` inclusive lands
        the filing in `SUBMITTED`; submission after the window close but at or before
        `maintenance_grace_close` lands it in `LATE_FILED`; anything earlier or later
        is `ERR_OUTSIDE_FILING_WINDOW`."

        Design: Corner/validations/submit_before_window_open_returns_outside_filing_window
        """
        _, record, evidence_ids = setup_record_with_verified_evidence(
            classes=(9,), specimen_date="2030-06-01T00:00:00Z")
        filing = create_maintenance_filing(record["id"], evidence_ids)
        # Window opens 2031-08-10; the clock sits at 2031-01-01.
        set_clock("2031-01-01T00:00:00Z")

        res = api.submit_maintenance_filing(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_OUTSIDE_FILING_WINDOW, expected_status=422)
        assert get_maintenance_filing(filing["id"])["status"] == "PREPARED"


class TestRecordMaintenanceCycle:
    def test_record_maintenance_due_and_acceptance_cycle(self, api, paralegal_headers,
                                                         partner_headers):
        """PRD §3.2: "When the logical clock reaches `maintenance_window_open`, a
        `REGISTERED` record enters `MAINTENANCE_DUE`."
        PRD §3.2: "If a maintenance filing of the record is accepted, the record
        returns to `REGISTERED` and all three maintenance horizons advance by ten
        years."
        PRD §3.9: "Submission within the closed interval from
        `maintenance_window_open` through `maintenance_window_close` inclusive lands
        the filing in `SUBMITTED`"

        Design: Corner/state_machines/record_maintenance_due_and_acceptance_cycle
        """
        _, record, evidence_ids = setup_record_with_verified_evidence(
            classes=(9,), specimen_date="2031-06-01T00:00:00Z")
        filing = create_maintenance_filing(record["id"], evidence_ids)
        # Window opens exactly at 2031-08-10T00:00:00Z (inclusive reach).
        set_clock("2031-08-10T00:00:00Z")
        assert get_record(record["id"])["status"] == "MAINTENANCE_DUE"

        submitted = validate_success(
            api.submit_maintenance_filing(filing["id"], paralegal_headers), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["is_late"] is False
        # 1 class: base 40000 + STANDARD surcharge 4000 = 44000, no late fee.
        assert submitted["fee_total_cents"] == 44000

        accepted = validate_success(
            api.office_decision_maintenance_filing(filing["id"],
                                                   {"decision": "ACCEPTED"},
                                                   partner_headers), 200)
        assert accepted["status"] == "ACCEPTED"

        record_after = get_record(record["id"])
        assert record_after["status"] == "REGISTERED"
        assert_instant_equal(record_after["maintenance_window_open"],
                             "2041-08-10T00:00:00Z", "maintenance_window_open +10y")
        assert_instant_equal(record_after["maintenance_window_close"],
                             "2042-08-10T00:00:00Z", "maintenance_window_close +10y")
        assert_instant_equal(record_after["maintenance_grace_close"],
                             "2043-02-10T00:00:00Z", "maintenance_grace_close +10y")

    def test_record_cancelled_after_grace_expiry(self, api, paralegal_headers):
        """PRD §3.2: "If the clock passes `maintenance_grace_close` with no filing of
        the record in `SUBMITTED`, `LATE_FILED`, or `ACCEPTED`, the record is
        cancelled by the sweep, triggering the same moot cascade as an adverse
        challenge."

        Design: Corner/state_machines/record_cancelled_after_grace_expiry
        """
        _, record = setup_registered_record(classes=(9,))
        # Grace close is 2033-02-10T00:00:00Z; strict '>' — not yet cancelled at it.
        set_clock("2033-02-10T00:00:00Z")
        assert get_record(record["id"])["status"] == "MAINTENANCE_DUE"

        set_clock("2033-02-11T00:00:00Z")
        assert get_record(record["id"])["status"] == "CANCELLED"
