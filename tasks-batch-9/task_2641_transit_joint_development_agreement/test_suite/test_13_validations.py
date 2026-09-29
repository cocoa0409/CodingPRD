"""Field-rule checks: the conditions that make a rule fire, the conditions that
leave it inert, and which of two simultaneous failures the caller is told about."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    assert_score,
    build_context,
    build_occupied_facility_context,
    build_site,
    build_valuation,
    create_agreement_payload,
    create_local_only_site_payload,
    create_proposal_payload,
    create_site_payload,
    create_staging_window_payload,
    make_developer_headers,
    read_shared_facility,
    read_site,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
    UNKNOWN_UUIDS,
)

JUNIPER_SITE = {
    "site_code": "TJD-C-030",
    "name": "Juniper Ridge Parcel",
    "address_line": "30 Juniper Rdg",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


def _site(site_code: str, name: str, address_line: str) -> dict:
    site = dict(JUNIPER_SITE)
    site.update(site_code=site_code, name=name, address_line=address_line)
    return site


class TestSiteCodeUniqueness:
    """The inventory-wide uniqueness rule on the parcel's own code."""

    def test_reusing_a_site_code_is_refused_and_leaves_one_parcel(
            self, api, real_estate_officer):
        """PRD §3.1: "The payload names the parcel with a `site_code` of between 1
        and 32 characters that must be unique across the whole inventory — reusing
        an existing code is refused with `ERR_DUPLICATE_SITE_CODE`". PRD §2.11 puts
        that rule among the "Remaining business constraints — duplicate site code",
        and a refused create leaves nothing behind, since "the checks are evaluated
        in a strict, fixed order and the **first** failing check decides the
        response."

        Design: Corner/validations/corner_duplicate_site_code_rejected
        """
        set_logical_clock()
        original = build_site(site_code="TJD-C-026", name="Juniper Depot Parcel",
                              address_line="26 Juniper Dp", parcel_area_sqft=61000,
                              acquisition_funding_source="FEDERAL_GRANT",
                              federal_interest_pct=2.5)

        response = api.create_site(create_local_only_site_payload(
            site_code="TJD-C-026", name="Juniper Depot Parcel Duplicate",
            address_line="27 Juniper Dp", parcel_area_sqft=40000),
            real_estate_officer)

        validate_error(response, ApiErrorId.DUPLICATE_SITE_CODE)
        assert read_site(original["id"])["name"] == "Juniper Depot Parcel"
        sites, _ = validate_paginated(api.list_sites(real_estate_officer))
        codes = [site["site_code"] for site in sites]
        assert codes.count("TJD-C-026") == 1


class TestLocalOnlyFederalInterest:
    """The zero-federal-interest rule binds one funding source and spares the
    other two."""

    def test_local_only_with_a_federal_claim_is_refused_while_mixed_is_accepted(
            self, api, real_estate_officer):
        """PRD §3.1: "A parcel bought entirely with local money cannot carry a
        federal claim, so when `acquisition_funding_source` is `LOCAL_ONLY` the
        `federal_interest_pct` must be exactly 0; any other value is a malformed
        request and is refused with `ERR_INVALID_REQUEST`." The rule is written
        against one of three declared sources — "`acquisition_funding_source` is one
        of `FEDERAL_GRANT`, `LOCAL_ONLY` or `MIXED`, and `federal_interest_pct` is
        the percentage of the parcel's value in which the grantor retains an
        interest, between 0 and 100 inclusive" — so the identical body under `MIXED`
        is a well-formed create, and PRD §4 says "Creating a new resource returns
        HTTP 201".

        Design: Corner/validations/corner_local_only_site_with_nonzero_federal_interest_rejected
        """
        set_logical_clock()

        refused = api.create_site(create_site_payload(
            site_code="TJD-C-028", name="Juniper West Parcel",
            address_line="28 Juniper W", parcel_area_sqft=44000,
            acquisition_funding_source="LOCAL_ONLY", federal_interest_pct=2.5),
            real_estate_officer)

        validate_error(refused, ApiErrorId.INVALID_REQUEST)
        sites, _ = validate_paginated(api.list_sites(real_estate_officer))
        assert "TJD-C-028" not in [site["site_code"] for site in sites]

        accepted = api.create_site(create_site_payload(
            site_code="TJD-C-029", name="Juniper North Parcel",
            address_line="29 Juniper N", parcel_area_sqft=44000,
            acquisition_funding_source="MIXED", federal_interest_pct=2.5),
            real_estate_officer)

        site = validate_success(accepted, expected_status=201)
        assert site["acquisition_funding_source"] == "MIXED"
        assert_score(site["federal_interest_pct"], 2.5, "federal_interest_pct")


class TestJointUseCommitment:
    """The joint-use rule fires from the solicitation's own flag."""

    def test_a_required_joint_use_refuses_the_uncommitted_bid_and_admits_the_committed_one(
            self, api, real_estate_officer):
        """PRD §3.3: "omitting or falsifying `joint_use_committed` while the
        solicitation's `joint_use_required` is true reports
        `ERR_JOINT_USE_NOT_COMMITTED`". Committing repairs the same body, and the
        commitment buys no points: PRD §3.3 works these very inputs — "a
        `GROUND_LEASE` proposal offering 2,400,000 cents of annual rent, with 50
        affordable units out of 200 total, 600 boardings of ridership uplift and a
        design compliance score of 88, responding to a solicitation with a benchmark
        of 48,500,000 cents and an affordable minimum of 15 percent, from a
        prequalified developer" gives "the raw sum is 84.79, the penalty is 0.00, and
        the `evaluation_score` is 84.79". PRD §3.3 also fixes the count: "A submitted
        proposal lands in `SUBMITTED` with `rank` null, and the parent solicitation's
        `responsive_proposal_count` is incremented by 1."

        Design: Corner/validations/corner_joint_use_requirement_applies_only_when_flagged
        """
        ctx = build_context(stage="SOLICITATION_ISSUED",
                            site_overrides=_site("TJD-C-031",
                                                 "Juniper Court Parcel",
                                                 "31 Juniper Ct"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"joint_use_required": True,
                                                    "benchmark_value_cents": 48_500_000,
                                                    "affordable_housing_min_pct": 15})
        developer_headers = make_developer_headers(ctx["developer"]["id"])
        assert ctx["solicitation"]["joint_use_required"] is True

        refused = api.create_proposal(
            ctx["solicitation"]["id"],
            create_proposal_payload(ctx["developer"]["id"],
                                    joint_use_committed=False),
            developer_headers)

        validate_error(refused, ApiErrorId.JOINT_USE_NOT_COMMITTED)

        accepted = api.create_proposal(
            ctx["solicitation"]["id"],
            create_proposal_payload(ctx["developer"]["id"],
                                    joint_use_committed=True),
            developer_headers)

        proposal = validate_success(accepted, expected_status=201)
        assert proposal["joint_use_committed"] is True
        assert proposal["status"] == "SUBMITTED"
        assert_score(proposal["evaluation_score"], 84.79, "evaluation_score")
        solicitation = validate_success(api.get_solicitation(
            ctx["solicitation"]["id"], real_estate_officer))
        assert solicitation["responsive_proposal_count"] == 1
        proposals, meta = validate_paginated(api.list_proposals(
            real_estate_officer,
            params={"solicitation_id": ctx["solicitation"]["id"]}))
        assert meta["total_count"] == 1
        assert [record["id"] for record in proposals] == [proposal["id"]]


class TestAffordableMinimumOnSubmission:
    """A bid under the published affordable floor never becomes a response."""

    def test_ten_percent_against_a_fifteen_percent_minimum_is_refused(
            self, api, real_estate_officer):
        """PRD §3.3: "the proposal's affordable share falling below the
        solicitation's `affordable_housing_min_pct` reports
        `ERR_AFFORDABLE_MINIMUM_NOT_MET`", where "The affordable share itself,
        `affordable_pct`, is one hundred multiplied by `affordable_units` divided by
        `total_units`, rounded half up to two decimal places." Twenty units of two
        hundred is 10.00 against a minimum of 15, and only a success moves the
        counter: "A submitted proposal lands in `SUBMITTED` with `rank` null, and the
        parent solicitation's `responsive_proposal_count` is incremented by 1."

        Design: Corner/validations/corner_proposal_below_affordable_minimum_rejected
        """
        ctx = build_context(stage="SOLICITATION_ISSUED",
                            site_overrides=_site("TJD-C-032",
                                                 "Juniper Bend Parcel",
                                                 "32 Juniper Bnd"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"affordable_housing_min_pct": 15,
                                                    "joint_use_required": False})

        response = api.create_proposal(
            ctx["solicitation"]["id"],
            create_proposal_payload(ctx["developer"]["id"],
                                    affordable_units=20, total_units=200,
                                    joint_use_committed=False),
            make_developer_headers(ctx["developer"]["id"]))

        validate_error(response, ApiErrorId.AFFORDABLE_MINIMUM_NOT_MET)
        solicitation = validate_success(api.get_solicitation(
            ctx["solicitation"]["id"], real_estate_officer))
        assert solicitation["responsive_proposal_count"] == 0
        _, meta = validate_paginated(api.list_proposals(
            real_estate_officer,
            params={"solicitation_id": ctx["solicitation"]["id"]}))
        assert meta["total_count"] == 0


class TestResponseDeadlineOnSubmission:
    """The same bid, valid on the first of August and refused once the clock
    passes the deadline."""

    def test_a_bid_one_day_past_the_deadline_is_refused_and_the_notice_stays_issued(
            self, api, real_estate_officer):
        """PRD §3.3: "a solicitation whose `response_deadline` the logical clock has
        already reached reports `ERR_RESPONSE_DEADLINE_PASSED`". PRD §2.5 supplies
        the clock: "Deadlines, expiries and every `*_at` timestamp derive from a
        **logical clock** rather than the host wall clock" and "Before the clock is
        ever set, the logical current UTC instant is `2026-08-01T00:00:00Z`". Nothing
        about the notice changes — PRD §3.3 gives `ISSUED` only to issuance, "On
        success the solicitation moves `DRAFT → ISSUED` and `issued_at` is stamped
        from the logical clock" — and the counter only moves on a success, since "A
        submitted proposal lands in `SUBMITTED` with `rank` null, and the parent
        solicitation's `responsive_proposal_count` is incremented by 1."

        Design: Corner/validations/corner_proposal_after_response_deadline_rejected
        """
        ctx = build_context(stage="SOLICITATION_ISSUED",
                            site_overrides=_site("TJD-C-033",
                                                 "Juniper Grove Parcel",
                                                 "33 Juniper Grv"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={
                                "response_deadline": "2026-09-15T00:00:00Z",
                                "joint_use_required": False})
        assert ctx["solicitation"]["status"] == "ISSUED"
        set_logical_clock("2026-09-16T00:00:00Z")

        response = api.create_proposal(
            ctx["solicitation"]["id"],
            create_proposal_payload(ctx["developer"]["id"],
                                    joint_use_committed=False),
            make_developer_headers(ctx["developer"]["id"]))

        validate_error(response, ApiErrorId.RESPONSE_DEADLINE_PASSED)
        solicitation = validate_success(api.get_solicitation(
            ctx["solicitation"]["id"], real_estate_officer))
        assert solicitation["status"] == "ISSUED"
        assert solicitation["responsive_proposal_count"] == 0


class TestStagingEnvelopeBeatsCapacity:
    """One request that breaks both the envelope and the bay ceiling, then the
    same request pulled inside the envelope."""

    @staticmethod
    def _facility_with_four_bays_taken():
        return build_occupied_facility_context(
            bays_occupied=4,
            start_at="2026-08-16T08:00:00Z",
            end_at="2026-08-20T08:00:00Z",
            negotiation_via="award",
            period_start_date="2026-08-15",
            period_end_date="2027-01-15",
            site_overrides=_site("TJD-C-034", "Juniper Yard Parcel",
                                 "34 Juniper Yd"),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"joint_use_committed": False},
            resolution_number="R-2026-134")

    def test_the_envelope_refusal_speaks_first_and_the_capacity_refusal_survives_it(
            self, api, real_estate_officer):
        """PRD §2.11: "On requesting a staging window, an interval outside the
        permitted envelope reports `ERR_STAGING_WINDOW_OUTSIDE_TERM` even when the
        same interval would also exceed the facility's bay capacity." PRD §3.9 draws
        the envelope: "the envelope opens at midnight UTC on that period's
        `start_date` and closes at midnight UTC 180 days after its `end_date`, the
        closing instant itself being excluded", and it keeps the lower check live —
        "The peak-occupancy test described below is then also applied at request
        time, so a window whose interval would already push the facility over its
        `total_bay_capacity` is refused at request with
        `ERR_STAGING_CAPACITY_EXCEEDED` rather than being parked in `REQUESTED` for
        the operations manager to discover; the envelope refusal takes precedence
        when both would fail." The occupancy is the overlapping approved bays: PRD
        §3.9 says "Two windows overlap if and only if the first starts strictly
        before the second ends and the second starts strictly before the first ends",
        and "Peak occupancy is then the candidate window's own `bays_occupied` plus
        the largest simultaneous total the conflicting windows reach". Neither
        refusal writes anything, because PRD §3.9 gives the bump only to success: "A
        successful request creates the window in `REQUESTED` with `capacity_released`
        false and `rejection_reason` null, and bumps the shared facility's `version`
        by 1". PRD §3.9 also fixes the ledger: "it is the `total_bay_capacity` less
        the sum of `bays_occupied` across that facility's `APPROVED` windows".

        Design: Corner/validations/corner_staging_window_outside_term_beats_capacity_exceeded
        """
        ctx = self._facility_with_four_bays_taken()
        facility_before = read_shared_facility(ctx["facility"]["id"])
        assert facility_before["available_bay_capacity"] == 2
        developer_headers = make_developer_headers(ctx["developer"]["id"])

        outside = api.create_staging_window(
            create_staging_window_payload(
                ctx["agreement"]["id"], ctx["facility"]["id"],
                facility_before["version"],
                start_at="2026-08-10T00:00:00Z", end_at="2026-08-18T00:00:00Z",
                bays_occupied=3, purpose="Early utility relocation"),
            developer_headers)

        validate_error(outside, ApiErrorId.STAGING_WINDOW_OUTSIDE_TERM)

        inside = api.create_staging_window(
            create_staging_window_payload(
                ctx["agreement"]["id"], ctx["facility"]["id"],
                facility_before["version"],
                start_at="2026-08-16T08:00:00Z", end_at="2026-08-18T08:00:00Z",
                bays_occupied=3, purpose="Utility relocation inside term"),
            developer_headers)

        validate_error(inside, ApiErrorId.STAGING_CAPACITY_EXCEEDED)
        facility_after = read_shared_facility(ctx["facility"]["id"])
        assert facility_after["available_bay_capacity"] == 2
        assert facility_after["version"] == facility_before["version"]
        _, meta = validate_paginated(api.list_staging_windows(
            real_estate_officer,
            params={"shared_facility_id": ctx["facility"]["id"]}))
        assert meta["total_count"] == 1


class TestAffordableShareExactlyAtMinimum:
    """A commitment sitting exactly on the published minimum: the gates pass and
    the affordable bonus stays out of the credit rate."""

    def test_thirty_of_two_hundred_clears_the_minimum_without_earning_the_bonus(
            self, api, real_estate_officer):
        """PRD §3.3 fixes the score at the minimum, where affordable points "start at
        a base of fifteen and add half a point for each whole percentage point by
        which the proposal's `affordable_pct` exceeds the solicitation's
        `affordable_housing_min_pct`, rounded half up to two decimal places and then
        capped at 25.00; a proposal exactly at the minimum therefore scores the bare
        15.00." Against the PRD's worked case, whose "raw sum is 84.79, the penalty
        is 0.00, and the `evaluation_score` is 84.79" with "affordable points are
        15.00 plus half a point for each of the ten percentage points of headroom,
        giving 20.00", the same bid at the bare minimum scores 79.79. PRD §3.6 lets
        the draft through — "The committed affordable share — one hundred multiplied
        by `affordable_units_committed` divided by `total_units` — must be at least
        the `affordable_housing_min_pct` of the solicitation that produced the
        referenced proposal, otherwise `ERR_AFFORDABLE_MINIMUM_NOT_MET`" — while
        keeping the credit bonus out, since PRD §3.6 gives it only when "the
        committed affordable share — `affordable_units_committed` divided by
        `total_units`, as a fraction — is at least twenty hundredths". The subtotal is
        the PRD's own: "a `GROUND_LEASE` with 2,000,000 cents of base rent,
        12,000,000 cents of projected gross revenue and a five-hundredths revenue
        share yields a participation of 600,000 and a subtotal of 2,600,000, which
        falls in the eight-hundredths tier", so at eight hundredths alone the credit
        is 208,000 and the annual revenue 2,392,000, and PRD §3.6 capitalises it —
        "For a `GROUND_LEASE` it is the `annual_revenue_to_agency_cents` just
        computed, capitalised over twenty years by simple integer multiplication" —
        giving 47,840,000, which clears the below-market floor of 36,375,000. PRD
        §3.7: "On success the agreement advances `DRAFTING → AGENCY_REVIEW`".

        Design: Corner/validations/corner_agreement_affordable_share_exactly_at_minimum_passes
        """
        ctx = build_context(
            stage="DRAFTING", negotiation_via="award",
            site_overrides=_site("TJD-C-035", "Juniper Field Parcel",
                                 "35 Juniper Fld"),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False,
                                    "benchmark_value_cents": 48_500_000,
                                    "affordable_housing_min_pct": 15},
            proposal_overrides={"affordable_units": 30, "total_units": 200,
                                "joint_use_committed": False},
            agreement_overrides={"affordable_units_committed": 30,
                                 "total_units": 200,
                                 "joint_use_committed": False})

        assert_score(ctx["proposal"]["affordable_pct"], 15.00, "affordable_pct")
        assert_score(ctx["proposal"]["evaluation_score"], 79.79,
                     "evaluation_score")
        assert_money(ctx["valuation"]["permissible_floor_cents"], 36_375_000,
                     "permissible_floor_cents")
        assert_money(ctx["agreement"]["capital_credit_cents"], 208_000,
                     "capital_credit_cents")
        assert_money(ctx["agreement"]["annual_revenue_to_agency_cents"],
                     2_392_000, "annual_revenue_to_agency_cents")
        assert_money(ctx["agreement"]["consideration_value_cents"], 47_840_000,
                     "consideration_value_cents")

        response = api.submit_agreement_for_review(ctx["agreement"]["id"],
                                                   real_estate_officer)

        submitted = validate_success(response)
        assert submitted["negotiation_status"] == "AGENCY_REVIEW"


class TestClockExpiryBlocksSubmission:
    """The clock alone closes the dealing window, and the untouched agreement can
    no longer be sent to review."""

    def test_moving_past_the_end_date_expires_the_period_and_blocks_the_submission(
            self, api, real_estate_officer):
        """PRD §2.5: "Every exclusive negotiation period whose status is `ACTIVE` or
        `EXTENDED` and whose `end_date` falls strictly before the calendar date of
        the new instant becomes `EXPIRED`; the proposal each newly expired period was
        holding drops from `SELECTED` to `REJECTED`; and every site left with no
        `ACTIVE` or `EXTENDED` period and no agreement in `EXECUTED` returns from
        `UNDER_AGREEMENT` to `SOLICITATION_READY`", and the move "reports the new
        `current_utc` together with `expired_negotiation_period_ids`, the list of
        exclusive negotiation period identifiers that the move expired". PRD §3.5
        says what that leaves of the agreement: "Any agreement referencing the
        expired period's proposal keeps whatever `negotiation_status` it holds —
        nothing about the agreement changes — but from that moment on it can no
        longer be advanced to review, and the attempt is refused with
        `ERR_NEGOTIATION_PERIOD_EXPIRED`." PRD §3.7 places that check second among
        its five: "The exclusive negotiation period holding this agreement's proposal
        must still be `ACTIVE` or `EXTENDED` with the logical clock's date on or
        before its `end_date`, otherwise `ERR_NEGOTIATION_PERIOD_EXPIRED`."

        Design: Corner/validations/corner_submit_for_review_blocked_after_clock_expires_negotiation_period
        """
        # The period is opened through the §3.4 award path because only that path
        # derives `SUBMITTED → SELECTED` on the held proposal; §3.5's direct grant
        # "never selects the proposal", so §2.5's expiry hop — "the proposal each
        # newly expired period was holding drops from `SELECTED` to `REJECTED`" —
        # would have no premise.
        ctx = build_context(stage="DRAFTING", negotiation_via="award",
                            period_start_date="2026-08-15",
                            period_end_date="2026-10-15",
                            site_overrides=_site("TJD-C-036",
                                                 "Juniper Landing Parcel",
                                                 "36 Juniper Lnd"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False},
                            agreement_overrides={"joint_use_committed": False})
        assert ctx["agreement"]["negotiation_status"] == "DRAFTING"

        clock = set_logical_clock("2026-10-16T00:00:00Z")
        assert ctx["period"]["id"] in clock["expired_negotiation_period_ids"]

        response = api.submit_agreement_for_review(ctx["agreement"]["id"],
                                                   real_estate_officer)

        validate_error(response, ApiErrorId.NEGOTIATION_PERIOD_EXPIRED)
        period = validate_success(api.get_negotiation_period(
            ctx["period"]["id"], real_estate_officer))
        assert period["status"] == "EXPIRED"
        proposal = validate_success(api.get_proposal(ctx["proposal"]["id"],
                                                     real_estate_officer))
        assert proposal["status"] == "REJECTED"
        assert read_site(ctx["site"]["id"])["status"] == "SOLICITATION_READY"
        agreement = validate_success(api.get_agreement(ctx["agreement"]["id"],
                                                       real_estate_officer))
        assert agreement["negotiation_status"] == "DRAFTING"


class TestBodyForeignKeyBeforeSiteState:
    """A bogus body reference is answered before the parcel's own state is even
    consulted."""

    def test_the_unknown_developer_answers_first_and_the_real_one_reaches_the_state_check(
            self, api, real_estate_officer):
        """PRD §2.9: "Foreign keys supplied in a request body are resolved after
        every path segment has been resolved, and among themselves in body-field
        declaration order: `site_id`, then `developer_id`, then `proposal_id`, then
        `valuation_id`, then `jda_id`, then `shared_facility_id`. An unknown body
        reference reports `ERR_SITE_NOT_FOUND`, `ERR_DEVELOPER_NOT_FOUND`,
        `ERR_PROPOSAL_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND` or `ERR_SHARED_FACILITY_NOT_FOUND`
        respectively." PRD §2.11 orders "Existence of every body foreign key, in
        declaration order (§2.9)" ahead of "Lifecycle-state checks on the records
        involved", and adds that "the checks are evaluated in a strict, fixed order
        and the **first** failing check decides the response." Once every reference
        resolves, PRD §3.6's own first check speaks: "The site must be
        `UNDER_AGREEMENT`, otherwise `ERR_SITE_NOT_UNDER_AGREEMENT`".

        Design: Corner/validations/corner_unknown_developer_fk_resolved_before_site_state_check
        """
        ctx = build_context(stage="PROPOSAL",
                            site_overrides=_site("TJD-C-037",
                                                 "Juniper Crossing Parcel",
                                                 "37 Juniper Crs"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False})
        valuation = build_valuation(ctx["site"]["id"])
        assert ctx["site"]["status"] == "SOLICITATION_READY"
        assert valuation["status"] == "DRAFT"

        unknown = api.create_agreement(
            create_agreement_payload(ctx["site"]["id"],
                                     UNKNOWN_UUIDS["DEVELOPER"],
                                     ctx["proposal"]["id"], valuation["id"],
                                     joint_use_committed=False),
            real_estate_officer)

        validate_error(unknown, ApiErrorId.DEVELOPER_NOT_FOUND)

        resolved = api.create_agreement(
            create_agreement_payload(ctx["site"]["id"],
                                     ctx["developer"]["id"],
                                     ctx["proposal"]["id"], valuation["id"],
                                     joint_use_committed=False),
            real_estate_officer)

        validate_error(resolved, ApiErrorId.SITE_NOT_UNDER_AGREEMENT)
        _, meta = validate_paginated(api.list_agreements(
            real_estate_officer, params={"site_id": ctx["site"]["id"]}))
        assert meta["total_count"] == 0
