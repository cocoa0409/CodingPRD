"""Member complaints and the directory correction pipeline (PRD §3.6, §3.7 link 4)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_complaint_payload, create_correction_payload, create_member_payload,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing, create_member, create_evaluation,
    finalize_evaluation, get_listing, setup_listed_network, setup_complaint,
    confirm_complaint,
    make_member_headers, make_compliance_officer_headers,
    make_network_manager_headers,
)

NM = TEST_USERS["network_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestComplaintStateBeatsTemporal:
    def _setup_removed_listing(self):
        ctx = setup_listed_network(county_fips="06023", enrolled_member_count=100,
                                   listing_overrides={"display_name": "Heart Fifteen",
                                                      "phone": "555-0115"})
        listing = ctx["listing"]
        validate_success(api_client.patch_listing(
            listing["id"], {"expected_listing_version": listing["version"],
                            "to_status": "REMOVED"}, NM))
        member = create_member(ctx["region"]["id"], member_ref="M-9001",
                               full_name="Ann Lee")
        return ctx, member

    def test_removed_listing_error_beats_expired_window(self, api):
        """PRD §3.6: "The listing must not be `REMOVED` (else `ERR_LISTING_REMOVED`),
        and the listing's location's region must equal the member's `region_id` (else
        `ERR_LISTING_NOT_IN_MEMBER_REGION`)."
        PRD §2.7: "After all referents exist, state-machine preconditions evaluate (the
        various `ERR_*_INVALID_*`, `ERR_*_NOT_*` 409 codes). Segregation-of-duties on
        correction verification (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) runs next, then
        temporal and window guards (`ERR_CYCLE_NOT_YET_ADVANCEABLE`,
        `ERR_COMPLAINT_WINDOW_EXPIRED`, `ERR_PROBE_DATE_ORDER`,
        `ERR_EXCUSE_WINDOW_INVALID`), then cross-entity referential coherence
        (`ERR_LOCATION_PROVIDER_MISMATCH`, `ERR_LISTING_NOT_IN_MEMBER_REGION`,
        `ERR_CORRECTION_LISTING_MISMATCH`, `ERR_SPECIALTY_STANDARD_MISSING`), then
        uniqueness and overlap constraints (`ERR_NPI_DUPLICATE`, `ERR_REGION_DUPLICATE`,
        `ERR_MEMBER_REF_DUPLICATE`, `ERR_STANDARD_DUPLICATE`,
        `ERR_LISTING_ALREADY_LISTED`, `ERR_CYCLE_WINDOW_OVERLAP`,
        `ERR_CYCLE_ALREADY_ACTIVE`, `ERR_EXCUSE_WINDOW_OVERLAP`,
        `ERR_EVALUATION_ALREADY_OPEN`)."

        Design: Difficulty/priority_pair_validation_conflict/file_complaint_state_error_beats_temporal_error
        """
        ctx, member = self._setup_removed_listing()
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_complaint(
            create_complaint_payload(ctx["listing"]["id"], error_type="WRONG_PHONE",
                                     error_observed_date="2026-04-01",
                                     description="phone disconnected"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LISTING_REMOVED)
        assert resp.status_code == 409, (
            "state error (409) must beat the expired-window temporal error (422)")

    def test_removed_listing_error_fires_when_window_is_fine(self, api):
        """PRD §3.2: "Removal is terminal; a `REMOVED` listing may not be republished,
        may not receive new complaints or corrections, and may not have new probes
        scheduled against it (any such attempt yields `ERR_LISTING_REMOVED`)."

        Design: Difficulty/priority_pair_validation_conflict/file_complaint_state_error_beats_temporal_error
        """
        ctx, member = self._setup_removed_listing()
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_complaint(
            create_complaint_payload(ctx["listing"]["id"], error_type="WRONG_PHONE",
                                     error_observed_date="2026-07-15",
                                     description="phone disconnected last week"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LISTING_REMOVED)


class TestComplaintFilingWindow:
    def test_complaint_window_exactly_90_days_allowed_91_rejected(self, api):
        """PRD §3.6: "The filing window is 90 days: the difference between the filing
        date and `error_observed_date` must not exceed 90 days, and
        `error_observed_date` must not be in the future; violation yields
        `ERR_COMPLAINT_WINDOW_EXPIRED`."

        Design: Corner/validations/complaint_window_exactly_90_days_allowed_91_rejected
        """
        ctx = setup_listed_network(county_fips="06077", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L65",
                                                      "phone": "555-0165"})
        member = create_member(ctx["region"]["id"], member_ref="M-9065",
                               full_name="Dee Park")
        set_clock("2026-07-30T00:00:00Z")
        ok = validate_success(api.create_complaint(
            create_complaint_payload(ctx["listing"]["id"],
                                     error_observed_date="2026-05-01",
                                     description="90 days exactly"),
            make_member_headers(member["id"])), expected_status=201)
        assert ok["status"] == "OPEN", "exactly 90 days is inside the inclusive window"
        too_late = api.create_complaint(
            create_complaint_payload(ctx["listing"]["id"],
                                     error_observed_date="2026-04-30",
                                     description="91 days"),
            make_member_headers(member["id"]))
        validate_error(too_late, ApiErrorId.ERR_COMPLAINT_WINDOW_EXPIRED)


class TestComplaintCorrectionLinkage:
    def test_complaint_confirm_spawns_correction_and_verify_closes_complaint(self, api):
        """PRD §3.6: "A `CONFIRMED_ERROR` outcome requires `correction_changes` to be
        present and non-empty (else `ERR_INVALID_REQUEST`); it stamps `confirmed_at`,
        increments `version`, spawns a `DirectoryCorrection` on the complaint's listing
        with `complaint_id` set to the complaint, `changes` taken from
        `correction_changes`, `submitted_by_user_id` set to the literal string
        `system:adjudication`, status `SUBMITTED`, and `sla_due_at` 72 hours out, and
        sets the listing's `has_confirmed_data_error` to true (bumping the listing's
        `version`)."
        PRD §3.6: "An `approve` value of true (the default) transitions the correction
        to `VERIFIED`: `verified_at` is stamped, `verified_by_user_id` records the
        verifier, `is_late` is computed as whether `verified_at` falls strictly after
        `sla_due_at`, the correction's `changes` are applied to the listing's
        correction-mutable fields (bumping the listing's `version`), and any linked
        complaint still in `CONFIRMED_ERROR` cascades to `CLOSED` while the listing's
        `has_confirmed_data_error` flips back to false."

        Design: Corner/state_machines/complaint_confirm_spawns_correction_and_verify_closes_complaint
        """
        ctx = setup_listed_network(county_fips="06065", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L53",
                                                      "phone": "555-0153"})
        filed = setup_complaint(ctx["region"], ctx["listing"],
                                observed_date="2026-04-28",
                                description="phone number disconnected")
        complaint, correction = confirm_complaint(
            filed["complaint"]["id"], correction_changes={"phone": "555-9999"},
            notes="verified with carrier")
        assert complaint["status"] == "CONFIRMED_ERROR"
        assert correction["status"] == "SUBMITTED"
        assert correction["complaint_id"] == complaint["id"]
        assert correction["submitted_by_user_id"] == "system:adjudication"
        flagged = get_listing(ctx["listing"]["id"])
        assert flagged["has_confirmed_data_error"] is True
        verified = validate_success(api.verify_correction(
            correction["id"], {"approve": True},
            make_compliance_officer_headers("co-auditor-9")))
        assert verified["status"] == "VERIFIED"
        assert verified["is_late"] is False, "verified well inside the 72-hour SLA"
        closed = validate_success(api.get_complaint(complaint["id"], CO))
        assert closed["status"] == "CLOSED"
        listing = get_listing(ctx["listing"]["id"])
        assert listing["phone"] == "555-9999", "verified changes are applied to the listing"
        assert listing["has_confirmed_data_error"] is False

    def test_correction_reject_leaves_complaint_open(self, api):
        """PRD §3.6: "An `approve` value of false transitions the correction to
        `REJECTED`; the linked complaint, if any, remains in `CONFIRMED_ERROR`, the
        listing's data-error flag remains set, and a fresh correction may be submitted
        against the same listing."

        Design: Corner/state_machines/correction_reject_leaves_complaint_open
        """
        ctx = setup_listed_network(county_fips="06067", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L55",
                                                      "phone": "555-0155"})
        filed = setup_complaint(ctx["region"], ctx["listing"],
                                observed_date="2026-04-28", error_type="WRONG_ADDRESS",
                                description="office moved")
        complaint, correction = confirm_complaint(
            filed["complaint"]["id"],
            correction_changes={"office_hours_note": "moved to 55 B St"})
        rejected = validate_success(api.verify_correction(
            correction["id"], {"approve": False},
            make_compliance_officer_headers("co-auditor-9")))
        assert rejected["status"] == "REJECTED"
        after = validate_success(api.get_complaint(complaint["id"], CO))
        assert after["status"] == "CONFIRMED_ERROR", "rejection must not close the complaint"
        listing = get_listing(ctx["listing"]["id"])
        assert listing["office_hours_note"] is None, "rejection applies no changes"
        assert listing["has_confirmed_data_error"] is True


class TestCorrectionGuards:
    def test_manual_correction_listing_mismatch_rejected(self, api):
        """PRD §3.6: "When `complaint_id` is present, the referenced complaint must
        currently be in `CONFIRMED_ERROR` and its `listing_id` must equal the
        correction's `listing_id` (else `ERR_CORRECTION_LISTING_MISMATCH`)."

        Design: Corner/errors/manual_correction_listing_mismatch_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06095", name="Mariposa2")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        provider = create_provider(legal_name="P79")
        loca = create_location(provider["id"], region["id"], address_line="79 A St")
        locb = create_location(provider["id"], region["id"], address_line="79 B St")
        la = publish_listing(create_listing(provider["id"], loca["id"],
                                            display_name="A79", phone="555-0179")["id"])
        lb = publish_listing(create_listing(provider["id"], locb["id"],
                                            display_name="B79", phone="555-0180")["id"])
        member = create_member(region["id"], member_ref="M-9079", full_name="Gus Han")
        complaint = validate_success(api.create_complaint(
            create_complaint_payload(la["id"], error_type="OTHER",
                                     error_observed_date="2026-04-25", description="on A"),
            make_member_headers(member["id"])), expected_status=201)
        resp = api.create_correction(
            {"listing_id": lb["id"], "complaint_id": complaint["id"],
             "changes": {"phone": "555-0000"}}, NM)
        validate_error(resp, ApiErrorId.ERR_CORRECTION_LISTING_MISMATCH)

    def test_complaint_against_listing_outside_member_region_rejected(self, api):
        """PRD §3.6: "The listing must not be `REMOVED` (else `ERR_LISTING_REMOVED`),
        and the listing's location's region must equal the member's `region_id` (else
        `ERR_LISTING_NOT_IN_MEMBER_REGION`)."

        Design: Corner/errors/complaint_against_listing_outside_member_region_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        reg1 = create_region(county_fips="06097", name="R-One")
        reg2 = create_region(county_fips="06099", name="R-Two")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        provider = create_provider(legal_name="P81")
        loc = create_location(provider["id"], reg1["id"], address_line="81 A St")
        listing = publish_listing(create_listing(provider["id"], loc["id"],
                                                 display_name="L81", phone="555-0181")["id"])
        member = create_member(reg2["id"], member_ref="M-9081", full_name="Hana Ip")
        resp = api.create_complaint(
            create_complaint_payload(listing["id"], error_type="WRONG_ADDRESS",
                                     error_observed_date="2026-04-25",
                                     description="wrong region member"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_IN_MEMBER_REGION)

    def test_disenrolled_member_cannot_file_complaint(self, api):
        """PRD §3.6: "The call's `X-User-ID` must be the `id` of an existing `Member` —
        it becomes the complaint's `member_id` — and that member must be `ENROLLED`
        (else `ERR_MEMBER_NOT_ENROLLED`)."

        Design: Corner/errors/disenrolled_member_cannot_file_complaint
        """
        ctx = setup_listed_network(county_fips="06101", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L83",
                                                      "phone": "555-0183"})
        member = create_member(ctx["region"]["id"], member_ref="M-9083",
                               full_name="Ira Jo")
        validate_success(api.disenroll_member(member["id"], NM))
        resp = api.create_complaint(
            create_complaint_payload(ctx["listing"]["id"], error_type="OTHER",
                                     error_observed_date="2026-04-25",
                                     description="after disenroll"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ENROLLED)

    def test_correction_verify_same_user_segregation_rejected(self, api):
        """PRD §3.6: "Verification is performed by a `ComplianceOfficer` and enforces
        segregation of duties: the verifier's `X-User-ID` must differ from the
        correction's `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`
        (HTTP 403)."

        Design: Corner/rbac/correction_verify_same_user_segregation_rejected
        """
        ctx = setup_listed_network(county_fips="06113", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L89",
                                                      "phone": "555-0189"})
        correction = validate_success(api.create_correction(
            create_correction_payload(ctx["listing"]["id"],
                                      changes={"phone": "555-0200"}),
            make_network_manager_headers("nm-lead-1")), expected_status=201)
        same_user = api.verify_correction(
            correction["id"], {"approve": True},
            make_compliance_officer_headers("nm-lead-1"))
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        other = validate_success(api.verify_correction(
            correction["id"], {"approve": True},
            make_compliance_officer_headers("co-auditor-2")))
        assert other["status"] == "VERIFIED"


class TestPenaltySummary:
    def test_penalty_summary_computed_read_full_breakdown(self, api):
        """PRD §3.7: "The deficiency component is the sum over this evaluation's accrual
        events of each event's round-half-up-to-integer-cents amount — per-event
        rounding happens before summation, not after. The error component is 25,000
        cents per `MemberComplaint` whose `confirmed_at` falls inside the measurement
        period (the period is interpreted as running from the start of
        `period_start_date` through the end of `period_end_date`) and whose current
        status is `CONFIRMED_ERROR` or `CLOSED` — that is, ever-confirmed within the
        period — attributed to the evaluation via the complaint's listing's location's
        region. The late-correction component is 50,000 cents per `DirectoryCorrection`
        in `VERIFIED` status with `is_late` true and `verified_at` inside the period."
        PRD §3.7: "A computed penalty-summary read exposes the breakdown:
        `deficiency_penalties_cents`, `error_penalties_cents`,
        `late_correction_penalties_cents`, `total_penalty_cents`, and a `rows` array of
        per-line detail."

        Design: Corner/endpoints/penalty_summary_computed_read_full_breakdown
        """
        ctx = setup_listed_network(county_fips="06087", enrolled_member_count=2400,
                                   listing_overrides={"display_name": "L75",
                                                      "phone": "555-0175"})
        member = create_member(ctx["region"]["id"], member_ref="M-9075",
                               full_name="Eli Fox")
        set_clock("2026-06-05T09:00:00Z")
        complaint = validate_success(api.create_complaint(
            create_complaint_payload(ctx["listing"]["id"], error_type="NOT_ACCEPTING",
                                     error_observed_date="2026-06-01",
                                     description="refused new patient"),
            make_member_headers(member["id"])), expected_status=201)
        _confirmed, correction = confirm_complaint(
            complaint["id"], correction_changes={"accepts_new_patients": True})
        set_clock("2026-06-10T09:00:00Z")
        verified = validate_success(api.verify_correction(
            correction["id"], {"approve": True},
            make_compliance_officer_headers("co-auditor-7")))
        assert verified["is_late"] is True, (
            "verified 2026-06-10T09:00 after sla_due_at 2026-06-08T09:00")
        ev = create_evaluation(measurement_period="PS")
        finalize_evaluation(ev["id"])
        summary = validate_success(api.get_penalty_summary(ev["id"], NM))
        assert summary["deficiency_penalties_cents"] == 99990, (
            "9999 * 10 days * tier 1.0 * repeat 1.0")
        assert summary["error_penalties_cents"] == 25000, "one in-period confirmed error"
        assert summary["late_correction_penalties_cents"] == 50000, "one late verification"
        assert summary["total_penalty_cents"] == 174990
