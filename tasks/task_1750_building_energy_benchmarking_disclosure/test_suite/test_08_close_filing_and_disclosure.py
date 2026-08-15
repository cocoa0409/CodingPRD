"""Close-filing sweep, performance-shortfall fines, disclosure publication, archive guards (PRD §3.1, §3.2, §3.6, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certify_report,
    close_filing_cycle,
    create_and_open_cycle,
    create_building,
    create_owner,
    create_report,
    create_verifier,
    get_cycle,
    get_owner,
    list_fines,
    setup_report_scenario,
    submit_ctx,
    validate_error,
    validate_success,
    verify_report,
)

OFFICER = TEST_USERS["officer_headers"]
OFFICER2 = TEST_USERS["officer2_headers"]

FULL_YEAR_2027 = {
    "period_start": "2027-01-01T00:00:00Z",
    "period_end": "2028-01-01T00:00:00Z",
}


class TestCloseFilingSweep:
    def _setup_verified_peer_and_bare_building(self):
        """bV: verified report (eui 81.89, no shortfall). bN: covered, no report."""
        owner_v = create_owner(name="Owner V", contact_email="ov@x.com")
        owner_n = create_owner(name="Owner N", contact_email="on@x.com")
        verifier = create_verifier()
        cycle = create_and_open_cycle()

        ctx_v = setup_report_scenario(
            owner=owner_v,
            cycle=cycle,
            building_overrides={"address": "10 Main St"},
            usage_records=[dict(FULL_YEAR_2027, consumption_value=1200000)],
        )
        submit_ctx(ctx_v)
        verify_report(ctx_v, verifier)
        assert ctx_v["report"]["status"] == "VERIFIED"
        assert ctx_v["report"]["site_eui"] == pytest.approx(81.89, abs=0.005)

        building_n = create_building(
            owner_n["id"], address="11 Main St", gross_floor_area_sqft=30000
        )
        return owner_v, owner_n, cycle, ctx_v, building_n

    def test_close_filing_sweeps_non_compliance_fines(self, api):
        """PRD §3.1: "On success the cycle moves `OPEN → FILING_CLOSED` and a
        two-stage sweep runs. First, every covered building with no report in
        `VERIFIED` or `CERTIFIED` for this cycle receives a `FineAssessment` of
        `fine_type` `NON_COMPLIANCE` in `ASSESSED` status whose
        `provisional_amount_cents` equals the cycle's `non_compliance_fine_cents`."

        The verified peer building draws no fine at all.

        Design: Difficulty/transitive_cascade/close_filing_creates_fines_and_restricts_owner
        """
        _ov, _on, cycle, ctx_v, building_n = self._setup_verified_peer_and_bare_building()

        closed = close_filing_cycle(cycle["id"])
        assert closed["status"] == "FILING_CLOSED"

        fines_n = list_fines(building_id=building_n["id"])
        assert len(fines_n) == 1
        assert fines_n[0]["fine_type"] == "NON_COMPLIANCE"
        assert fines_n[0]["status"] == "ASSESSED"
        assert fines_n[0]["provisional_amount_cents"] == 500000

        fines_v = list_fines(building_id=ctx_v["building"]["id"])
        assert fines_v == [], "verified building gets neither NON_COMPLIANCE nor shortfall"

    def test_close_filing_fine_flips_owner_standing(self, api):
        """PRD §3.1: "Each fine created by the sweep immediately recomputes the
        affected owner's exposure per §3.7, and an owner whose
        `outstanding_fines_cents` crosses above the restriction threshold flips to
        `RESTRICTED` standing as part of the same request."

        500000 > 100000: the non-compliant owner flips; the verified peer stays
        NORMAL at zero.

        Design: Difficulty/transitive_cascade/close_filing_creates_fines_and_restricts_owner
        """
        owner_v, owner_n, cycle, _ctx_v, _bn = self._setup_verified_peer_and_bare_building()

        close_filing_cycle(cycle["id"])

        owner_n_after = get_owner(owner_n["id"])
        assert owner_n_after["outstanding_fines_cents"] == 500000
        assert owner_n_after["standing"] == "RESTRICTED"

        owner_v_after = get_owner(owner_v["id"])
        assert owner_v_after["outstanding_fines_cents"] == 0
        assert owner_v_after["standing"] == "NORMAL"


class TestPerformanceShortfall:
    def _setup_shortfall_pair(self):
        """b1 at site_eui 94.50 (exactly the rounded tolerance threshold);
        b2 at 94.51 (one cent of EUI above). Default baseline 100 -> target 90.00;
        tolerance 5% -> threshold 94.50."""
        owner = create_owner()
        verifier = create_verifier()
        cycle = create_and_open_cycle()

        ctx1 = setup_report_scenario(
            owner=owner,
            cycle=cycle,
            building_overrides={"address": "45 Main St"},
            unit_specs=[("U1", 20000, "OFFICE"), ("U2", 10000, "RETAIL")],
            consent_indexes=(0, 1),
            usage_records=[dict(FULL_YEAR_2027, consumption_value=47250)],
            account_overrides={"commodity": "NATURAL_GAS"},
        )
        submit_ctx(ctx1)
        verify_report(ctx1, verifier)

        ctx2 = setup_report_scenario(
            owner=owner,
            cycle=cycle,
            building_overrides={"address": "46 Main St"},
            unit_specs=[("U1", 20000, "OFFICE"), ("U2", 10000, "RETAIL")],
            consent_indexes=(0, 1),
            usage_records=[dict(FULL_YEAR_2027, consumption_value=47255)],
            account_overrides={"commodity": "NATURAL_GAS"},
        )
        submit_ctx(ctx2)
        verify_report(ctx2, verifier)
        return cycle, ctx1, ctx2

    def test_shortfall_at_exact_threshold_incurs_no_fine(self, api):
        """PRD §3.6: "Otherwise the tolerance threshold is the report's `target_eui`
        inflated by the standard's `shortfall_tolerance_pct` — the target multiplied
        by one plus the tolerance expressed as a fraction of one hundred, rounded
        half-up to two decimals **before** any comparison."
        PRD §3.6: "When the report's currently stored `site_eui` — after any
        corrections — is strictly greater than that rounded threshold (a value
        exactly at the threshold incurs no fine), the shortfall percentage is the
        excess over the threshold divided by `target_eui`, multiplied by one hundred
        and rounded half-up to two decimals."

        47250 therms -> site_eui 94.50 == threshold 94.50: no fine.

        Design: Corner/calculations/c_performance_shortfall_boundary_and_fee
        """
        cycle, ctx1, _ctx2 = self._setup_shortfall_pair()
        assert ctx1["report"]["site_eui"] == pytest.approx(94.50, abs=0.005)
        assert ctx1["report"]["target_eui"] == pytest.approx(90.00, abs=0.005)

        close_filing_cycle(cycle["id"])

        assert list_fines(building_id=ctx1["building"]["id"]) == []

    def test_shortfall_above_threshold_assesses_fine(self, api):
        """PRD §3.6: "When the report's currently stored `site_eui` — after any
        corrections — is strictly greater than that rounded threshold (a value
        exactly at the threshold incurs no fine), the shortfall percentage is the
        excess over the threshold divided by `target_eui`, multiplied by one hundred
        and rounded half-up to two decimals. The fine is the building's
        `gross_floor_area_sqft` multiplied by the standard's
        `fine_rate_cents_per_sqft` multiplied by that shortfall percentage, rounded
        half-up to whole cents, and finally capped at the standard's
        `performance_fine_cap_cents` — the cap applies last."

        47255 therms -> site_eui 94.51 > 94.50: shortfall rounds to 0.01 pct;
        fine 50000 * 5 * 0.01 = 2500 cents (below the 1000000 cap).

        Design: Corner/calculations/c_performance_shortfall_boundary_and_fee
        """
        cycle, _ctx1, ctx2 = self._setup_shortfall_pair()
        assert ctx2["report"]["site_eui"] == pytest.approx(94.51, abs=0.005)

        close_filing_cycle(cycle["id"])

        fines = list_fines(building_id=ctx2["building"]["id"])
        assert len(fines) == 1
        assert fines[0]["fine_type"] == "PERFORMANCE_SHORTFALL"
        assert fines[0]["status"] == "ASSESSED"
        assert fines[0]["provisional_amount_cents"] == 2500


class TestDisclosurePublication:
    def test_publish_freezes_included_count_and_publishes_cycle(self, api):
        """PRD §3.9: "The publication moves `DRAFT → PUBLISHED`, stamps
        `published_at`, and freezes `included_report_count` as the count of the
        cycle's reports then in `VERIFIED` or `CERTIFIED`. When the cycle was still
        `FILING_CLOSED`, the same action moves the cycle itself to `PUBLISHED` and
        sets the cycle's `published_at`"

        b1 VERIFIED + b2 CERTIFIED are counted; b3's never-submitted DRAFT is not.

        Design: Corner/endpoints/ep_publish_freezes_included_count
        """
        owner = create_owner()
        verifier = create_verifier()
        cycle = create_and_open_cycle()

        ctx1 = setup_report_scenario(
            owner=owner, cycle=cycle, building_overrides={"address": "81 Main St"}
        )
        submit_ctx(ctx1)
        verify_report(ctx1, verifier)

        ctx2 = setup_report_scenario(
            owner=owner, cycle=cycle, building_overrides={"address": "82 Main St"}
        )
        submit_ctx(ctx2)
        verify_report(ctx2, verifier)
        certified = certify_report(ctx2["report"]["id"], OFFICER2)
        assert certified["status"] == "CERTIFIED"

        # Third building: DRAFT report, never submitted.
        building3 = create_building(owner["id"], address="83 Main St")
        create_report(building3["id"], cycle["id"], owner["id"])

        close_filing_cycle(cycle["id"])
        publication = validate_success(
            api.create_disclosure_publication(cycle["id"], OFFICER), 201
        )
        published = validate_success(api.publish_disclosure(publication["id"], OFFICER))
        assert published["status"] == "PUBLISHED"
        assert published["included_report_count"] == 2
        assert published["published_at"] is not None

        cycle_after = get_cycle(cycle["id"])
        assert cycle_after["status"] == "PUBLISHED"
        assert cycle_after["published_at"] is not None

    def test_second_draft_publication_rejected(self, api):
        """PRD §3.9: "A `ComplianceOfficer` creates a draft publication for a cycle
        once filing is closed: the cycle must be `FILING_CLOSED` or `PUBLISHED`, else
        `ERR_CYCLE_NOT_CLOSED`, and no other `DRAFT` publication may exist for the
        cycle, else `ERR_DRAFT_PUBLICATION_EXISTS`."

        Design: Corner/validations/v_second_draft_publication_rejected
        """
        cycle = create_and_open_cycle()
        close_filing_cycle(cycle["id"])
        validate_success(api.create_disclosure_publication(cycle["id"], OFFICER), 201)

        resp = api.create_disclosure_publication(cycle["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_DRAFT_PUBLICATION_EXISTS)

    def test_publication_create_requires_closed_cycle(self, api):
        """PRD §3.9: "A `ComplianceOfficer` creates a draft publication for a cycle
        once filing is closed: the cycle must be `FILING_CLOSED` or `PUBLISHED`, else
        `ERR_CYCLE_NOT_CLOSED`, and no other `DRAFT` publication may exist for the
        cycle, else `ERR_DRAFT_PUBLICATION_EXISTS`."

        Design: Corner/validations/v_publication_create_before_close_rejected
        """
        cycle = create_and_open_cycle()
        resp = api.create_disclosure_publication(cycle["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CLOSED)


class TestArchiveGuards:
    def test_archive_blocked_by_open_fine(self, api):
        """PRD §3.2: "Two guards protect the transition — the building must have no
        fine assessment in `ASSESSED` or `NOTICED` (otherwise `ERR_OPEN_FINES_EXIST`)
        and no benchmark report in `DRAFT`, `SUBMITTED`, or `FLAGGED` (otherwise
        `ERR_OPEN_REPORTS_EXIST`)"

        The close-filing sweep left an ASSESSED NON_COMPLIANCE fine on this building.

        Design: Corner/validations/v_archive_with_open_fine_rejected
        """
        owner = create_owner()
        cycle = create_and_open_cycle()
        building = create_building(owner["id"], address="71 Main St")
        close_filing_cycle(cycle["id"])
        fines = list_fines(building_id=building["id"])
        assert len(fines) == 1 and fines[0]["status"] == "ASSESSED"

        resp = api.archive_building(building["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_OPEN_FINES_EXIST)
        still = validate_success(api.get_building(building["id"], OFFICER))
        assert still["status"] == "ACTIVE"

    def test_archive_blocked_by_draft_report(self, api):
        """PRD §3.2: "Two guards protect the transition — the building must have no
        fine assessment in `ASSESSED` or `NOTICED` (otherwise `ERR_OPEN_FINES_EXIST`)
        and no benchmark report in `DRAFT`, `SUBMITTED`, or `FLAGGED` (otherwise
        `ERR_OPEN_REPORTS_EXIST`)"

        A DRAFT report alone blocks the archive; no fines exist (cycle still OPEN).

        Design: Corner/validations/v_archive_with_draft_report_rejected
        """
        owner = create_owner()
        cycle = create_and_open_cycle()
        building = create_building(owner["id"], address="72 Main St")
        create_report(building["id"], cycle["id"], owner["id"])

        resp = api.archive_building(building["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_OPEN_REPORTS_EXIST)
        still = validate_success(api.get_building(building["id"], OFFICER))
        assert still["status"] == "ACTIVE"
