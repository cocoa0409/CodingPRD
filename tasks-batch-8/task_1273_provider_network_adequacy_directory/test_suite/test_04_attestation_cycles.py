"""Attestation cycles: windows, advance gates, response rate, close sweep (PRD §3.4/§3.5)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_cycle_payload,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing, create_cycle, get_cycle, get_listing,
    list_records, record_for_listing, respond_record, setup_listed_network,
    setup_open_cycle_for_listings,
    make_provider_rep_headers,
)

NM = TEST_USERS["network_manager_headers"]


def _setup_two_listings_one_provider():
    set_clock("2026-05-01T00:00:00Z")
    region = create_region(county_fips="06005", name="Butte")
    create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
    provider = create_provider(legal_name="Heart Five")
    loc1 = create_location(provider["id"], region["id"], address_line="5 Elm St")
    loc2 = create_location(provider["id"], region["id"], address_line="7 Elm St")
    lst1 = publish_listing(create_listing(provider["id"], loc1["id"], display_name="Five A",
                                          phone="555-0105")["id"])
    lst2 = publish_listing(create_listing(provider["id"], loc2["id"], display_name="Five B",
                                          phone="555-0106")["id"])
    return {"region": region, "provider": provider, "listings": [lst1, lst2]}


class TestAttestationResponseRateVariants:
    def _setup_cycle_with_two_records(self):
        ctx = _setup_two_listings_one_provider()
        opened = setup_open_cycle_for_listings(cycle_label="2026-Q2A")
        rec1 = record_for_listing(opened["cycle"]["id"], ctx["listings"][0]["id"])
        rec2 = record_for_listing(opened["cycle"]["id"], ctx["listings"][1]["id"])
        return ctx, opened["cycle"], rec1, rec2

    def test_lenient_numerator_counts_attested_plus_correction_requested(self, api):
        """PRD §3.4: "The cycle's computed counters are `total_records` (records of this
        cycle not in `CANCELLED`), `pending_count`, `responded_count` (records in
        `ATTESTED` plus records in `CORRECTION_REQUESTED`), and `non_responsive_count`."

        Design: Difficulty/dual_variant_calc/attestation_response_rate_strict_vs_lenient
        """
        ctx, cycle, rec1, rec2 = self._setup_cycle_with_two_records()
        respond_record(rec1["id"], ctx["provider"]["id"], data_accurate=True)
        respond_record(rec2["id"], ctx["provider"]["id"], data_accurate=False,
                       corrected_payload={"phone": "555-0199"})
        cycle = get_cycle(cycle["id"])
        assert cycle["total_records"] == 2
        assert cycle["responded_count"] == 2, (
            "lenient numerator counts ATTESTED + CORRECTION_REQUESTED")
        assert cycle["pending_count"] == 0

    def test_strict_numerator_counts_only_attested(self, api):
        """PRD §3.4: "From these the response rate is derived on read in two variants:
        the strict rate divides the count of `ATTESTED` records by `total_records`, and
        the lenient rate divides the count of `ATTESTED` plus `CORRECTION_REQUESTED`
        records by `total_records`."
        PRD §3.5: "the system spawns a `DirectoryCorrection` on the record's listing
        with `changes` taken from `corrected_payload`, `complaint_id` null,
        `submitted_by_user_id` set to the responding `ProviderRep`'s `X-User-ID`, status
        `SUBMITTED`, and `sla_due_at` set 72 hours after the spawn timestamp."

        Design: Difficulty/dual_variant_calc/attestation_response_rate_strict_vs_lenient
        """
        ctx, cycle, rec1, rec2 = self._setup_cycle_with_two_records()
        respond_record(rec1["id"], ctx["provider"]["id"], data_accurate=True)
        respond_record(rec2["id"], ctx["provider"]["id"], data_accurate=False,
                       corrected_payload={"phone": "555-0199"})
        attested = list_records({"cycle_id": cycle["id"], "status": "ATTESTED"})
        assert len(attested) == 1, "strict numerator counts only clean ATTESTED records"
        corrections, _meta = validate_paginated(api_client.list_corrections(
            NM, params={"listing_id": ctx["listings"][1]["id"]}))
        assert len(corrections) == 1
        assert corrections[0]["changes"] == {"phone": "555-0199"}
        assert corrections[0]["status"] == "SUBMITTED"
        assert corrections[0]["complaint_id"] is None


class TestCycleWindowOverlap:
    def test_half_open_adjacency_allowed(self, api):
        """PRD §3.4: "The cycle's window from `open_date` (inclusive) to
        `outreach_close_date` (exclusive) must not overlap any existing cycle's window —
        adjacency is allowed, so one cycle's `outreach_close_date` may equal another's
        `open_date` — otherwise the create is rejected with `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/attestation_cycle_half_open_adjacency_allowed
        """
        set_clock("2026-05-01T00:00:00Z")
        create_cycle(cycle_label="C1", open_date="2026-05-01", due_date="2026-05-10",
                     outreach_close_date="2026-05-20")
        resp = api.create_cycle(create_cycle_payload(
            cycle_label="C2", open_date="2026-05-20", due_date="2026-05-25",
            outreach_close_date="2026-05-31"), NM)
        data = validate_success(resp, expected_status=201)
        assert data["open_date"] == "2026-05-20", (
            "open == prior outreach_close is adjacency, not overlap, under half-open semantics")

    def test_true_overlap_rejected(self, api):
        """PRD §3.4: "The cycle's window from `open_date` (inclusive) to
        `outreach_close_date` (exclusive) must not overlap any existing cycle's window —
        adjacency is allowed, so one cycle's `outreach_close_date` may equal another's
        `open_date` — otherwise the create is rejected with `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/attestation_cycle_half_open_adjacency_allowed
        """
        set_clock("2026-05-01T00:00:00Z")
        create_cycle(cycle_label="C1", open_date="2026-05-01", due_date="2026-05-10",
                     outreach_close_date="2026-05-20")
        create_cycle(cycle_label="C2", open_date="2026-05-20", due_date="2026-05-25",
                     outreach_close_date="2026-05-31")
        resp = api.create_cycle(create_cycle_payload(
            cycle_label="C3", open_date="2026-05-30", due_date="2026-06-05",
            outreach_close_date="2026-06-10"), NM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)


class TestCycleAdvanceOrdering:
    def test_temporal_error_beats_singleton_constraint(self, api):
        """PRD §3.4: "`SCHEDULED` → `OPEN` requires the clock date to be at or past
        `open_date` (else `ERR_CYCLE_NOT_YET_ADVANCEABLE` — the temporal check runs
        before the singleton check so a too-early advance surfaces its own error) and no
        other cycle currently in `OPEN` or `OUTREACH` (else `ERR_CYCLE_ALREADY_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/cycle_advance_temporal_beats_constraint
        """
        set_clock("2026-05-05T00:00:00Z")
        c1 = create_cycle(cycle_label="C1")
        validate_success(api.advance_cycle(c1["id"], NM))
        c2 = create_cycle(cycle_label="C2", open_date="2026-06-01", due_date="2026-06-10",
                          outreach_close_date="2026-06-20")
        resp = api.advance_cycle(c2["id"], NM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_YET_ADVANCEABLE)
        assert resp.status_code == 422, (
            "temporal error (422) must beat the singleton constraint error (409)")

    def test_too_early_advance_without_any_active_cycle(self, api):
        """PRD §3.4: "`SCHEDULED` → `OPEN` requires the clock date to be at or past
        `open_date` (else `ERR_CYCLE_NOT_YET_ADVANCEABLE` — the temporal check runs
        before the singleton check so a too-early advance surfaces its own error) and no
        other cycle currently in `OPEN` or `OUTREACH` (else `ERR_CYCLE_ALREADY_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/cycle_advance_temporal_beats_constraint
        """
        set_clock("2026-05-01T00:00:00Z")
        c2 = create_cycle(cycle_label="C-late", open_date="2026-06-01",
                          due_date="2026-06-10", outreach_close_date="2026-06-20")
        resp = api.advance_cycle(c2["id"], NM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_YET_ADVANCEABLE)


class TestCycleStateMachine:
    def test_cycle_advance_from_closed_rejected(self, api):
        """PRD §3.4: "Advancing from any other state, or advancing a `CLOSED` cycle, is
        rejected with `ERR_CYCLE_INVALID_STATE`."

        Design: Corner/state_machines/cycle_advance_from_closed_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        cycle = create_cycle(cycle_label="T1")
        validate_success(api.advance_cycle(cycle["id"], NM))
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.advance_cycle(cycle["id"], NM))
        set_clock("2026-05-20T00:00:00Z")
        closed = validate_success(api.advance_cycle(cycle["id"], NM))
        assert closed["status"] == "CLOSED"
        resp = api.advance_cycle(cycle["id"], NM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE)

    def test_cycle_create_bad_date_order_invalid_request(self, api):
        """PRD §3.4: "The three dates must satisfy the strict ordering `open_date`
        before `due_date` before `outreach_close_date`; bad ordering is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/cycle_create_bad_date_order_invalid_request
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_cycle(create_cycle_payload(
            cycle_label="BAD", open_date="2026-05-10", due_date="2026-05-01",
            outreach_close_date="2026-05-20"), NM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_second_cycle_open_while_another_active_rejected(self, api):
        """PRD §3.4: "`SCHEDULED` → `OPEN` requires the clock date to be at or past
        `open_date` (else `ERR_CYCLE_NOT_YET_ADVANCEABLE` — the temporal check runs
        before the singleton check so a too-early advance surfaces its own error) and no
        other cycle currently in `OPEN` or `OUTREACH` (else `ERR_CYCLE_ALREADY_ACTIVE`)."

        Design: Corner/errors/second_cycle_open_while_another_active_rejected
        """
        set_clock("2026-05-05T00:00:00Z")
        c1 = create_cycle(cycle_label="A1")
        validate_success(api.advance_cycle(c1["id"], NM))
        c2 = create_cycle(cycle_label="A2", open_date="2026-05-25", due_date="2026-06-01",
                          outreach_close_date="2026-06-10")
        set_clock("2026-05-25T00:00:00Z")
        resp = api.advance_cycle(c2["id"], NM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_ALREADY_ACTIVE)


class TestCycleCloseSweep:
    def _setup_two_providers_cycle(self):
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06057", name="Stanislaus")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        pa = create_provider(legal_name="PA")
        pb = create_provider(legal_name="PB")
        la = create_location(pa["id"], region["id"], address_line="45 A St")
        lb = create_location(pb["id"], region["id"], address_line="46 A St")
        sa = publish_listing(create_listing(pa["id"], la["id"], display_name="LA",
                                            phone="555-0145")["id"])
        sb = publish_listing(create_listing(pb["id"], lb["id"], display_name="LB",
                                            phone="555-0146")["id"])
        cycle = create_cycle(cycle_label="T2")
        validate_success(api_client.advance_cycle(cycle["id"], NM))
        reca = record_for_listing(cycle["id"], sa["id"])
        recb = record_for_listing(cycle["id"], sb["id"])
        return {"pa": pa, "pb": pb, "sa": sa, "sb": sb, "cycle": cycle,
                "reca": reca, "recb": recb}

    def test_cycle_close_sweep_suppresses_nonresponsive_listings(self, api):
        """PRD §3.4: "`OUTREACH` → `CLOSED` requires the clock date at or past
        `outreach_close_date` (else `ERR_CYCLE_NOT_YET_ADVANCEABLE`); on this transition
        every record still in `PENDING` flips to `NON_RESPONSIVE` (link 1), each such
        record's listing — if still `LISTED` — transitions to `SUPPRESSED` with
        `suppress_reason` = `ATTESTATION_FAILURE` and `suppressed_at` stamped (link 2),
        and the cycle counters recompute so that `pending_count` falls to 0 while
        `non_responsive_count` rises (link 3)."

        Design: Corner/state_machines/cycle_close_sweep_suppresses_nonresponsive_listings
        """
        ctx = self._setup_two_providers_cycle()
        respond_record(ctx["reca"]["id"], ctx["pa"]["id"], data_accurate=True)
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.advance_cycle(ctx["cycle"]["id"], NM))
        recb_mid = validate_success(api.get_attestation_record(ctx["recb"]["id"], NM))
        assert recb_mid["outreach_attempts"] == 1, (
            "the OPEN -> OUTREACH hop increments outreach_attempts exactly once")
        set_clock("2026-05-20T00:00:00Z")
        closed = validate_success(api.advance_cycle(ctx["cycle"]["id"], NM))
        assert closed["status"] == "CLOSED"
        assert closed["pending_count"] == 0
        assert closed["non_responsive_count"] == 1
        sb = get_listing(ctx["sb"]["id"])
        assert sb["status"] == "SUPPRESSED"
        assert sb["suppress_reason"] == "ATTESTATION_FAILURE"
        assert sb["suppressed_at"] is not None
        sa = get_listing(ctx["sa"]["id"])
        assert sa["status"] == "LISTED", (
            "the conditional cascade must skip the attested provider's listing")


class TestLateAttestationReinstate:
    def _setup_suppressed_by_attestation_failure(self, fips, name):
        ctx = setup_listed_network(county_fips=fips, enrolled_member_count=100,
                                   listing_overrides={"display_name": name,
                                                      "phone": "555-0147"})
        cycle = create_cycle(cycle_label=f"T-{fips}")
        validate_success(api_client.advance_cycle(cycle["id"], NM))
        record = record_for_listing(cycle["id"], ctx["listing"]["id"])
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api_client.advance_cycle(cycle["id"], NM))
        set_clock("2026-05-20T00:00:00Z")
        validate_success(api_client.advance_cycle(cycle["id"], NM))
        return ctx, cycle, record

    def test_late_attestation_then_reinstate_after_cycle_close(self, api):
        """PRD §3.5: "A record in `NON_RESPONSIVE` may be responded to late, after its
        cycle has `CLOSED`."
        PRD §3.2: "A listing suppressed for `ATTESTATION_FAILURE` requires, before
        reinstatement, the existence of an `AttestationRecord` for this listing in
        `ATTESTED` or `CORRECTION_REQUESTED` status whose `responded_at` is strictly
        later than the listing's `suppressed_at`; otherwise the reinstate is rejected
        with `ERR_LISTING_ATTESTATION_UNRESOLVED`."

        Design: Corner/state_machines/late_attestation_then_reinstate_after_cycle_close
        """
        ctx, cycle, record = self._setup_suppressed_by_attestation_failure("06059", "L47")
        set_clock("2026-05-21T00:00:00Z")
        responded = respond_record(record["id"], ctx["provider"]["id"], data_accurate=True)
        assert responded["status"] == "ATTESTED"
        listing = get_listing(ctx["listing"]["id"])
        reinstated = validate_success(api.patch_listing(
            listing["id"],
            {"expected_listing_version": listing["version"], "to_status": "LISTED"}, NM))
        assert reinstated["status"] == "LISTED"
        assert reinstated["suppress_reason"] == "NONE"

    def test_reinstate_attestation_failure_without_response_rejected(self, api):
        """PRD §3.2: "A listing suppressed for `ATTESTATION_FAILURE` requires, before
        reinstatement, the existence of an `AttestationRecord` for this listing in
        `ATTESTED` or `CORRECTION_REQUESTED` status whose `responded_at` is strictly
        later than the listing's `suppressed_at`; otherwise the reinstate is rejected
        with `ERR_LISTING_ATTESTATION_UNRESOLVED`."

        Design: Corner/state_machines/reinstate_attestation_failure_without_response_rejected
        """
        ctx, cycle, record = self._setup_suppressed_by_attestation_failure("06061", "L49")
        listing = get_listing(ctx["listing"]["id"])
        assert listing["suppress_reason"] == "ATTESTATION_FAILURE"
        resp = api.patch_listing(
            listing["id"],
            {"expected_listing_version": listing["version"], "to_status": "LISTED"}, NM)
        validate_error(resp, ApiErrorId.ERR_LISTING_ATTESTATION_UNRESOLVED)
        assert get_listing(listing["id"])["status"] == "SUPPRESSED"
