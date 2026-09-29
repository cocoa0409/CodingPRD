"""Endpoint contracts and the immediacy of every derived consequence.

The side-effect-free royalty preview, the flat reverse-lookup filters that stand
in for nested paths, the two mutually exclusive licence field sets, the clock
sweep's three identifier arrays, the composition round trip that must leave both
status axes alone, and the rule that a cascade is already complete inside the
response of the write that caused it.
"""

from test_helpers import (
    ACCOUNTANT_ONE,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    assert_cents_equal,
    assert_blanket_axes,
    assert_composer_money,
    assert_composition_axes,
    assert_created,
    assert_credit_exposure,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_same_instant,
    assert_statement_figures,
    assert_status,
    assert_sweep_lists,
    composer_version,
    composition_version,
    ledger_entries,
    make_composer_headers,
    make_licensee_headers,
    new_active_blanket,
    new_cataloged_work,
    new_composer,
    new_active_agreement,
    new_fingerprint_match,
    new_licensee,
    new_tier,
    open_usage_report,
    read_composer,
    read_composition,
    read_licensee,
)
from test_helpers import factories as build

CLOCK_ORIGIN = "2026-08-01T00:00:00Z"


def _page_ids(response):
    """The ids on a list page plus the filter's `total_count`."""
    rows, meta = assert_page(response)
    return [row["id"] for row in rows], meta["total_count"]


def _per_use_deal(api, work, tier, licensee, **request_overrides):
    """Carry one request SUBMITTED -> UNDER_REVIEW -> QUOTED -> ACCEPTED."""
    request = assert_created(
        api.create_sync_request(
            build.sync_request_payload(
                work.composition_id, licensee["id"], tier["id"], **request_overrides
            ),
            LICENSING_AGENT,
        )
    )
    assert_ok(api.review_sync_request(request["id"], None, LICENSING_AGENT))
    request = assert_ok(
        api.quote_sync_request(request["id"], build.quote_payload(14), LICENSING_AGENT)
    )
    return assert_ok(
        api.accept_sync_request(request["id"], None, make_licensee_headers(licensee["id"]))
    )


# ---------------------------------------------------------------------------
# The composer royalty preview
# ---------------------------------------------------------------------------


def _composer_with_one_adjustment(api):
    """One composer withholding 30% whose ledger holds a single 40000 adjustment."""
    composer = new_composer(
        api,
        display_name="Nadia Okoro",
        pro_affiliation="ASCAP",
        payee_country="US",
        tax_withholding_pct=0.30,
    )
    assert_created(
        api.create_royalty_ledger_entry(
            build.ledger_entry_payload(
                composer["id"], 40000, memo="Library-wide catalogue bonus"
            ),
            ACCOUNTANT_ONE,
        )
    )
    return composer


class TestRoyaltyPreviewIsASideEffectFreeRead:
    def test_preview_evaluates_the_whole_statement_calculation_for_the_window(self, api):
        """PRD §3.9: "The royalty preview takes a `period_start` and `period_end` and an
        optional `basis`, defaults the basis to `ACCRUAL`, and evaluates the whole
        statement calculation for that window without creating a statement and without
        stamping any entry."

        Design: Corner/endpoints/royalty_preview_is_a_side_effect_free_computed_read
        """
        composer = _composer_with_one_adjustment(api)
        params = build.preview_params(basis="ACCRUAL")

        by_accountant = assert_ok(
            api.get_royalty_preview(composer["id"], params, ACCOUNTANT_ONE)
        )
        by_composer = assert_ok(
            api.get_royalty_preview(
                composer["id"], params, make_composer_headers(composer["id"])
            )
        )

        for preview in (by_accountant, by_composer):
            assert preview["basis"] == "ACCRUAL"
            assert_cents_equal(preview["accrual_gross_cents"], 40000, "accrual_gross_cents")
            assert_cents_equal(preview["cash_gross_cents"], 40000, "cash_gross_cents")
            assert_cents_equal(preview["gross_cents"], 40000, "gross_cents")
            assert preview["included_entry_count"] == 1
            assert_cents_equal(
                preview["outstanding_advance_cents"], 0, "outstanding_advance_cents"
            )
            assert_cents_equal(preview["projected_recoup_cents"], 0, "projected_recoup_cents")
            assert_cents_equal(
                preview["projected_withholding_cents"], 12000, "projected_withholding_cents"
            )
            assert_cents_equal(preview["projected_net_cents"], 28000, "projected_net_cents")
            assert preview["projected_payout_status"] == "PAYABLE"

    def test_preview_writes_nothing_so_the_window_is_still_free_afterwards(self, api):
        """PRD §3.9: "Nothing is written and the composer's `version` does not change,
        which is exactly why the preview needs no version token."

        Design: Corner/endpoints/royalty_preview_is_a_side_effect_free_computed_read
        """
        composer = _composer_with_one_adjustment(api)
        before = composer_version(api, composer["id"])
        params = build.preview_params(basis="ACCRUAL")

        assert_ok(api.get_royalty_preview(composer["id"], params, ACCOUNTANT_ONE))
        assert_ok(
            api.get_royalty_preview(
                composer["id"], params, make_composer_headers(composer["id"])
            )
        )

        reread = read_composer(api, composer["id"])
        assert reread["version"] == before, "the preview must not move the composer's version"
        assert_composer_money(reread, accrued_unpaid_cents=40000)

        _ids, statement_count = _page_ids(
            api.list_royalty_statements({"composer_id": composer["id"]}, ACCOUNTANT_ONE)
        )
        assert statement_count == 0, "the preview must not create a statement"

        entries = ledger_entries(api, composer["id"])
        assert len(entries) == 1
        assert entries[0]["statement_id"] is None, "the preview must stamp nothing"

        statement = assert_created(
            api.create_royalty_statement(
                build.statement_payload(composer["id"], before), ACCOUNTANT_ONE
            )
        )
        assert_statement_figures(
            statement,
            gross_cents=40000,
            recouped_cents=0,
            withholding_cents=12000,
            net_payable_cents=28000,
            payout_status="PAYABLE",
            line_count=1,
        )


# ---------------------------------------------------------------------------
# Reverse lookup by query filter
# ---------------------------------------------------------------------------


def _two_sided_graph(api):
    """Two composers, two licensees, and one sibling row for every parent.

    Licensee one holds a per-use licence on work A, an active blanket carrying a
    due usage report, and a cue sheet hanging off the licence; licensee two holds
    a submitted request on work B. Work A also carries one detection and a claim.
    """
    work_a = new_cataloged_work(
        api,
        {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        {"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    work_b = new_cataloged_work(
        api,
        {"display_name": "Tomas Reyes", "pro_affiliation": "BMI"},
        {"sync_fee_share_pct": 40.00},
        title="Copper Skyline",
        duration_sec=150,
        tempo_bpm=110,
        genre="JAZZ",
        mood_tags=["CALM"],
        instrumentation=["GUITAR"],
    )
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee_one = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=10000000,
    )
    licensee_two = new_licensee(
        api, legal_name="Harbour Media", licensee_type="AGENCY", credit_limit_cents=10000000
    )

    request_a = _per_use_deal(
        api,
        work_a,
        tier,
        licensee_one,
        media_type="FILM",
        distribution_scale="NATIONAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
    )
    license_a = assert_created(
        api.create_license(
            build.per_use_license_payload(
                request_a["id"], composition_version(api, work_a.composition_id)
            ),
            LICENSING_AGENT,
        )
    )
    request_b = assert_created(
        api.create_sync_request(
            build.sync_request_payload(
                work_b.composition_id,
                licensee_two["id"],
                tier["id"],
                media_type="FILM",
                distribution_scale="LOCAL",
                requested_term_start="2026-09-01T00:00:00Z",
                requested_term_months=12,
            ),
            LICENSING_AGENT,
        )
    )

    blanket = new_active_blanket(
        api,
        licensee=licensee_one,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=60,
        pool_share_pct=25.00,
    )
    open_usage_report(api, blanket)

    cue_sheet = assert_created(
        api.create_cue_sheet(
            build.cue_sheet_payload(
                [build.cue(work_a.composition_id, "THEME", 30)],
                license_id=license_a["id"],
                production_title="Evening Bulletin",
                broadcast_date="2026-08-12T00:00:00Z",
                market_tier="NETWORK",
            ),
            LICENSING_AGENT,
        )
    )

    match = new_fingerprint_match(
        api,
        work_a.composition_id,
        source_platform="UGC_VIDEO",
        source_reference="vid-77120",
        matched_seconds=45,
        confidence_pct=96.0,
    )
    claim = assert_created(
        api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER)
    )

    return {
        "work_a": work_a,
        "work_b": work_b,
        "licensee_one": licensee_one,
        "licensee_two": licensee_two,
        "request_a": request_a,
        "request_b": request_b,
        "license_a": license_a,
        "blanket": blanket,
        "cue_sheet": cue_sheet,
        "match": match,
        "claim": claim,
    }


class TestReverseLookupByQueryFilter:
    def test_each_declared_filter_isolates_its_own_parent_row(self, api):
        """PRD §2.7: "Reverse lookup is therefore provided by query filters on the list
        endpoints rather than by nested paths."

        Design: Corner/endpoints/filtered_list_reverse_lookups_isolate_each_declared_parent
        """
        graph = _two_sided_graph(api)
        work_a = graph["work_a"]
        work_b = graph["work_b"]

        lookups = [
            (
                api.list_composer_agreements(
                    {"composer_id": work_a.composer_id}, RIGHTS_MANAGER
                ),
                work_a.agreement_id,
            ),
            (
                api.list_compositions({"agreement_id": work_b.agreement_id}, CATALOG_ADMIN),
                work_b.composition_id,
            ),
            (
                api.list_sync_requests(
                    {"licensee_id": graph["licensee_two"]["id"]}, LICENSING_AGENT
                ),
                graph["request_b"]["id"],
            ),
            (
                api.list_sync_requests(
                    {"license_id": graph["license_a"]["id"]}, LICENSING_AGENT
                ),
                graph["request_a"]["id"],
            ),
            (
                api.list_licenses({"composition_id": work_a.composition_id}, LICENSING_AGENT),
                graph["license_a"]["id"],
            ),
            (
                api.list_blanket_agreements(
                    {"licensee_id": graph["licensee_one"]["id"]}, LICENSING_AGENT
                ),
                graph["blanket"].agreement_id,
            ),
            (
                api.list_usage_reports(
                    {"blanket_agreement_id": graph["blanket"].agreement_id}, RIGHTS_MANAGER
                ),
                graph["blanket"].usage_report_id,
            ),
            (
                api.list_cue_sheets({"license_id": graph["license_a"]["id"]}, RIGHTS_MANAGER),
                graph["cue_sheet"]["id"],
            ),
            (
                api.list_fingerprint_matches(
                    {"composition_id": work_a.composition_id}, CATALOG_ADMIN
                ),
                graph["match"]["id"],
            ),
            (
                api.list_infringement_claims(
                    {"fingerprint_match_id": graph["match"]["id"]}, RIGHTS_MANAGER
                ),
                graph["claim"]["id"],
            ),
        ]

        for response, expected_id in lookups:
            ids, total_count = _page_ids(response)
            assert total_count == 1, f"expected exactly one row, got {total_count}"
            assert ids == [expected_id]

        entries = ledger_entries(api, work_a.composer_id)
        assert len(entries) == 1
        assert entries[0]["source_type"] == "SYNC_FEE"
        assert entries[0]["composer_id"] == work_a.composer_id

    def test_a_filter_matching_no_row_reports_a_total_count_of_zero(self, api):
        """PRD §2.3: "Both are echoed back in the envelope's `meta` object alongside
        `total_count`, the number of rows matching the filter before the page window is
        applied, and `has_more`, which is true when rows remain after the current
        window."

        Design: Corner/endpoints/filtered_list_reverse_lookups_isolate_each_declared_parent
        """
        graph = _two_sided_graph(api)

        blanket_licences, blanket_total = _page_ids(
            api.list_licenses(
                {"blanket_agreement_id": graph["blanket"].agreement_id}, LICENSING_AGENT
            )
        )
        assert blanket_total == 0, "the only licence is per-use, so no blanket parent matches"
        assert blanket_licences == []

        report_sheets, report_total = _page_ids(
            api.list_cue_sheets(
                {"usage_report_id": graph["blanket"].usage_report_id}, RIGHTS_MANAGER
            )
        )
        assert report_total == 0, "the cue sheet hangs off the licence, not the report"
        assert report_sheets == []


# ---------------------------------------------------------------------------
# Blanket-mode issuance
# ---------------------------------------------------------------------------


def _blanket_issuance_ground(api):
    """A catalogued work, an active compliant blanket, and two tiers.

    Tier BLK-OK may be cited by a blanket deal; tier PU-ONLY may not.
    """
    work = new_cataloged_work(
        api,
        {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        {"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    blanket_tier = new_tier(
        api,
        code="BLK-OK",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=400000,
        per_use_eligible=True,
        blanket_eligible=True,
    )
    per_use_only_tier = new_tier(
        api,
        code="PU-ONLY",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=400000,
        per_use_eligible=True,
        blanket_eligible=False,
    )
    licensee = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=10000000,
    )
    blanket = new_active_blanket(
        api,
        licensee=licensee,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=60,
        pool_share_pct=25.00,
    )
    return {
        "work": work,
        "blanket_tier": blanket_tier,
        "per_use_only_tier": per_use_only_tier,
        "licensee": licensee,
        "blanket": blanket,
        "version": composition_version(api, work.composition_id),
    }


def _issue_blanket_licence(api, ground, **overrides):
    payload = build.blanket_license_payload(
        ground["work"].composition_id,
        ground["blanket"].agreement_id,
        ground["blanket_tier"]["id"],
        ground["version"],
        media_type="BROADCAST_TV",
        distribution_scale="NATIONAL",
        term_start="2026-09-01T00:00:00Z",
        term_months=6,
    )
    # Overrides are applied to the built payload rather than splatted into the
    # factory call: `tier_id` is a positional parameter of
    # blanket_license_payload and `term_start` is already supplied above, so
    # splatting either one raises "got multiple values for keyword argument".
    payload.update(overrides)
    return api.create_license(payload, LICENSING_AGENT)


class TestBlanketModeIssuanceFieldSet:
    def test_blanket_mode_missing_its_own_required_fields_is_refused(self, api):
        """PRD §3.5: "A per-use request without a sync request, a blanket request missing
        any of its seven required fields, or a per-use request that also supplies a
        `blanket_agreement_id`, is refused with `ERR_LICENSE_MODE_FIELDS_INVALID`."

        Design: Corner/endpoints/blanket_mode_issuance_requires_its_own_field_set_and_eligible_tier
        """
        ground = _blanket_issuance_ground(api)

        response = api.create_license(
            {
                "license_mode": "BLANKET",
                "composition_id": ground["work"].composition_id,
                "blanket_agreement_id": ground["blanket"].agreement_id,
                "expected_composition_version": ground["version"],
            },
            LICENSING_AGENT,
        )
        assert_declared_error(response, "ERR_LICENSE_MODE_FIELDS_INVALID")

    def test_a_term_start_on_the_exclusive_coverage_end_falls_outside_coverage(self, api):
        """PRD §3.5: "For a blanket licence, `term_start` must fall inside the agreement's
        coverage interval, which is closed at `coverage_start` and open at
        `coverage_end`, or `ERR_TERM_OUTSIDE_COVERAGE`; and the blanket agreement must be
        in `ACTIVE` coverage with `reporting_status` `COMPLIANT` at the moment of
        issuance, or `ERR_BLANKET_NOT_ACTIVE`."

        Design: Corner/endpoints/blanket_mode_issuance_requires_its_own_field_set_and_eligible_tier
        """
        ground = _blanket_issuance_ground(api)

        response = _issue_blanket_licence(api, ground, term_start="2027-08-01T00:00:00Z")
        assert_declared_error(response, "ERR_TERM_OUTSIDE_COVERAGE")

    def test_a_tier_that_is_not_blanket_eligible_cannot_carry_a_blanket_deal(self, api):
        """PRD §3.5: "The tier must permit the mode: a per-use deal on a tier whose
        `per_use_eligible` is false, or a blanket deal on a tier whose `blanket_eligible`
        is false, is refused with `ERR_TIER_INCOMPATIBLE`."

        Design: Corner/endpoints/blanket_mode_issuance_requires_its_own_field_set_and_eligible_tier
        """
        ground = _blanket_issuance_ground(api)

        response = _issue_blanket_licence(
            api, ground, tier_id=ground["per_use_only_tier"]["id"]
        )
        assert_declared_error(response, "ERR_TIER_INCOMPATIBLE")

    def test_a_blanket_licence_carries_a_zero_fee_and_commits_no_credit(self, api):
        """PRD §3.5: "`final_fee_cents` is the final variant of the fee formula from §3.4,
        and is 0 for every blanket licence."

        Design: Corner/endpoints/blanket_mode_issuance_requires_its_own_field_set_and_eligible_tier
        """
        ground = _blanket_issuance_ground(api)

        licence = assert_created(_issue_blanket_licence(api, ground))
        assert licence["license_mode"] == "BLANKET"
        assert_status(licence, "ISSUED")
        assert_cents_equal(licence["final_fee_cents"], 0, "final_fee_cents")
        assert_cents_equal(
            licence["composer_sync_share_cents"], 0, "composer_sync_share_cents"
        )

        assert_credit_exposure(read_licensee(api, ground["licensee"]["id"]), 0, 0, 10000000)

    def test_a_zero_composer_share_appends_no_sync_fee_entry(self, api):
        """PRD §3.5: "When `composer_sync_share_cents` works out to 0, as it always does
        under a work-for-hire agreement, no entry is appended at all."

        Design: Corner/endpoints/blanket_mode_issuance_requires_its_own_field_set_and_eligible_tier
        """
        ground = _blanket_issuance_ground(api)
        assert_created(_issue_blanket_licence(api, ground))

        assert ledger_entries(api, ground["work"].composer_id) == []

    def test_blanket_term_end_is_the_inclusive_last_day_of_the_term(self, api):
        """PRD §3.5: "Its `term_end` is computed as `term_start` advanced by `term_months`
        calendar months and then pulled back one day, expressed as a date at midnight
        UTC; it is the inclusive last day of the term."

        Design: Corner/endpoints/blanket_mode_issuance_requires_its_own_field_set_and_eligible_tier
        """
        ground = _blanket_issuance_ground(api)

        licence = assert_created(_issue_blanket_licence(api, ground))
        assert licence["term_start"].startswith("2026-09-01")
        assert licence["term_end"].startswith("2027-02-28"), (
            "2026-09-01 plus six months, pulled back one day"
        )


# ---------------------------------------------------------------------------
# The clock sweep's identifier arrays
# ---------------------------------------------------------------------------


def _sweep_ground(api):
    """One licence and one blanket whose windows both close, plus one that lapses.

    Licensee one holds a one-month per-use licence and a blanket covering only
    August; licensee two holds a year-long blanket and files no report at all.
    """
    work = new_cataloged_work(
        api,
        {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        {"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee_one = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=10000000,
    )
    licensee_two = new_licensee(
        api, legal_name="Harbour Media", licensee_type="AGENCY", credit_limit_cents=10000000
    )

    request = _per_use_deal(
        api,
        work,
        tier,
        licensee_one,
        media_type="FILM",
        distribution_scale="NATIONAL",
        requested_term_start="2026-08-01T00:00:00Z",
        requested_term_months=1,
    )
    licence = assert_created(
        api.create_license(
            build.per_use_license_payload(
                request["id"], composition_version(api, work.composition_id)
            ),
            LICENSING_AGENT,
        )
    )

    closing_blanket = new_active_blanket(
        api,
        licensee=licensee_one,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2026-09-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=60,
        pool_share_pct=25.00,
    )
    lapsing_blanket = new_active_blanket(
        api,
        licensee=licensee_two,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=2400000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=60,
        pool_share_pct=20.00,
    )
    return {
        "work": work,
        "licensee_one": licensee_one,
        "licence": licence,
        "closing_blanket": closing_blanket,
        "lapsing_blanket": lapsing_blanket,
    }


class TestClockAdvanceSweepArrays:
    def test_one_advance_reports_all_three_identifier_arrays(self, api):
        """PRD §2.5: "The response body reports `current_utc`, the new clock value, plus
        `expired_license_ids`, `expired_blanket_agreement_ids` and
        `delinquent_blanket_agreement_ids` — the three arrays of identifiers the sweep
        touched."

        Design: Corner/endpoints/clock_advance_returns_expired_and_delinquent_id_arrays
        """
        ground = _sweep_ground(api)

        sweep = assert_ok(api.set_clock("2026-09-16T00:00:00Z", LICENSING_AGENT))
        assert_same_instant(sweep["current_utc"], "2026-09-16T00:00:00Z")
        assert_sweep_lists(
            sweep,
            expired_license_ids=[ground["licence"]["id"]],
            expired_blanket_agreement_ids=[ground["closing_blanket"].agreement_id],
            delinquent_blanket_agreement_ids=[ground["lapsing_blanket"].agreement_id],
        )

    def test_licence_expiry_releases_the_committed_spend(self, api):
        """PRD §3.5: "Expiry lowers the licensee's `committed_spend_cents` by
        `final_fee_cents` and raises `credit_available_cents` by the same amount, and
        recomputes the work's `active_license_count` and `exclusive_block_until` — so the
        work's block lifts as soon as no other exclusive licence in `ISSUED` or `ACTIVE`
        still covers it."

        Design: Corner/endpoints/clock_advance_returns_expired_and_delinquent_id_arrays
        """
        ground = _sweep_ground(api)
        assert_credit_exposure(
            read_licensee(api, ground["licensee_one"]["id"]), 877800, 0, 9122200
        )

        assert_ok(api.set_clock("2026-09-16T00:00:00Z", LICENSING_AGENT))

        licence = assert_ok(api.get_license(ground["licence"]["id"], LICENSING_AGENT))
        assert_status(licence, "EXPIRED")
        assert licence["term_end"].startswith("2026-08-31")
        assert_credit_exposure(
            read_licensee(api, ground["licensee_one"]["id"]), 0, 0, 10000000
        )
        assert read_composition(api, ground["work"].composition_id)["active_license_count"] == 0

    def test_a_blanket_that_reaches_expired_keeps_its_reporting_value(self, api):
        """PRD §2.9: "An `ACTIVE` agreement can be `DELINQUENT`, and an agreement that
        reaches `EXPIRED` keeps whatever reporting value it had."

        Design: Corner/endpoints/clock_advance_returns_expired_and_delinquent_id_arrays
        """
        ground = _sweep_ground(api)

        assert_ok(api.set_clock("2026-09-16T00:00:00Z", LICENSING_AGENT))

        closing = assert_ok(
            api.get_blanket_agreement(
                ground["closing_blanket"].agreement_id, LICENSING_AGENT
            )
        )
        assert_blanket_axes(closing, "EXPIRED", "COMPLIANT")
        assert closing["delinquent_since"] is None

    def test_one_overdue_period_past_its_grace_window_marks_the_blanket_delinquent(
        self, api
    ):
        """PRD §3.6: "One overdue period is enough: the agreement moves `COMPLIANT →
        DELINQUENT` and records `delinquent_since` from the clock."

        Design: Corner/endpoints/clock_advance_returns_expired_and_delinquent_id_arrays
        """
        ground = _sweep_ground(api)

        assert_ok(api.set_clock("2026-09-16T00:00:00Z", LICENSING_AGENT))

        lapsing = assert_ok(
            api.get_blanket_agreement(
                ground["lapsing_blanket"].agreement_id, LICENSING_AGENT
            )
        )
        assert_blanket_axes(lapsing, "ACTIVE", "DELINQUENT")
        assert_same_instant(lapsing["delinquent_since"], "2026-09-16T00:00:00Z")


# ---------------------------------------------------------------------------
# The composition round trip
# ---------------------------------------------------------------------------


def _governed_composer(api):
    """A composer whose agreement is ACTIVE, so its works may be catalogued."""
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(api, composer["id"], sync_fee_share_pct=40.00)
    return composer, agreement


def _ingest_harbour_lights(api, composer, agreement):
    return assert_created(
        api.create_composition(
            build.composition_payload(
                composer["id"],
                agreement["id"],
                title="Harbour Lights",
                duration_sec=180,
                tempo_bpm=130,
                genre="CINEMATIC",
                mood_tags=["EPIC", "HOPEFUL"],
                instrumentation=["STRINGS", "PIANO"],
            ),
            CATALOG_ADMIN,
        )
    )


class TestCompositionRoundTrip:
    def test_a_freshly_ingested_work_lands_on_both_axes_at_version_one(self, api):
        """PRD §3.2: "The work lands with `catalog_status` `INGESTED`,
        `availability_status` `AVAILABLE` and `version` 1."

        Design: Corner/endpoints/composition_crud_round_trip_preserves_status_axes_and_system_fields
        """
        composer, agreement = _governed_composer(api)

        composition = _ingest_harbour_lights(api, composer, agreement)
        assert_composition_axes(composition, "INGESTED", "AVAILABLE")
        assert composition["version"] == 1
        assert composition["active_license_count"] == 0
        assert composition["exclusive_block_until"] is None
        assert composition["open_claim_count"] == 0
        assert_credits_equal(
            composition["lifetime_performance_credits"], 0.00, "lifetime_performance_credits"
        )

        reread = read_composition(api, composition["id"])
        assert reread["title"] == "Harbour Lights"
        assert reread["duration_sec"] == 180
        assert reread["mood_tags"] == ["EPIC", "HOPEFUL"]
        assert reread["instrumentation"] == ["STRINGS", "PIANO"]

    def test_relevance_score_is_null_on_a_single_read_and_in_a_plain_list(self, api):
        """PRD §3.2: "A fifth figure, `relevance_score`, exists only inside a facet-search
        response: on a single-work read and in every plain list, it is null."

        Design: Corner/endpoints/composition_crud_round_trip_preserves_status_axes_and_system_fields
        """
        composer, agreement = _governed_composer(api)
        composition = _ingest_harbour_lights(api, composer, agreement)

        assert read_composition(api, composition["id"])["relevance_score"] is None

        rows, _meta = assert_page(
            api.list_compositions({"composer_id": composer["id"]}, CATALOG_ADMIN)
        )
        assert [row["relevance_score"] for row in rows] == [None]

    def test_a_metadata_revision_moves_neither_status_axis(self, api):
        """PRD §3.2: "Neither status axis is ever changed by a metadata revision."

        Design: Corner/endpoints/composition_crud_round_trip_preserves_status_axes_and_system_fields
        """
        composer, agreement = _governed_composer(api)
        composition = _ingest_harbour_lights(api, composer, agreement)
        cataloged = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
        assert_composition_axes(cataloged, "CATALOGED", "AVAILABLE")
        assert cataloged["version"] == 2

        revised = assert_ok(
            api.update_composition(
                composition["id"],
                {
                    "title": "Harbour Lights (2026 Remaster)",
                    "tempo_bpm": 128,
                    "genre": "CLASSICAL",
                    "mood_tags": ["EPIC", "UPLIFTING", "HOPEFUL"],
                },
                CATALOG_ADMIN,
            )
        )
        assert revised["title"] == "Harbour Lights (2026 Remaster)"
        assert revised["tempo_bpm"] == 128
        assert revised["genre"] == "CLASSICAL"
        assert revised["mood_tags"] == ["EPIC", "UPLIFTING", "HOPEFUL"]
        assert revised["instrumentation"] == ["STRINGS", "PIANO"]
        assert revised["version"] == 3
        assert revised["created_at"] == composition["created_at"]
        assert revised["active_license_count"] == 0
        assert_composition_axes(revised, "CATALOGED", "AVAILABLE")

        assert read_composition(api, composition["id"]) == revised

    def test_the_catalogue_status_filter_walks_only_the_matching_axis_value(self, api):
        """PRD §3.2: "Works can be read individually or listed with filters on
        `composer_id`, `agreement_id`, `catalog_status`, `availability_status`, `limit`
        and `offset`, which is how the catalogue is walked by composer or by agreement."

        Design: Corner/endpoints/composition_crud_round_trip_preserves_status_axes_and_system_fields
        """
        composer, agreement = _governed_composer(api)
        composition = _ingest_harbour_lights(api, composer, agreement)

        ids, ingested_total = _page_ids(
            api.list_compositions(
                {"composer_id": composer["id"], "catalog_status": "INGESTED"}, CATALOG_ADMIN
            )
        )
        assert ingested_total == 1
        assert ids == [composition["id"]]

        assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))

        ids, cataloged_total = _page_ids(
            api.list_compositions(
                {"composer_id": composer["id"], "catalog_status": "CATALOGED"}, CATALOG_ADMIN
            )
        )
        assert cataloged_total == 1
        assert ids == [composition["id"]]

        _ids, ingested_total = _page_ids(
            api.list_compositions(
                {"composer_id": composer["id"], "catalog_status": "INGESTED"}, CATALOG_ADMIN
            )
        )
        assert ingested_total == 0, "the work is no longer INGESTED"


# ---------------------------------------------------------------------------
# A cascade is complete inside the response of the write that caused it
# ---------------------------------------------------------------------------


def _accepted_film_deal(api):
    """An accepted request quoted at 1254000 against a 90000000 credit limit."""
    work = new_cataloged_work(
        api,
        {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        {"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee = new_licensee(
        api,
        legal_name="Northwind Pictures",
        licensee_type="PRODUCTION_COMPANY",
        credit_limit_cents=90000000,
    )
    request = _per_use_deal(
        api,
        work,
        tier,
        licensee,
        media_type="FILM",
        distribution_scale="NATIONAL",
        requested_term_start="2026-08-01T00:00:00Z",
        requested_term_months=12,
    )
    return {"work": work, "tier": tier, "licensee": licensee, "request": request}


class TestCascadeResultsAreFinalInTheWritesOwnResponse:
    def test_the_reservation_converts_inside_the_issuing_write_itself(self, api):
        """PRD §3.5: "For a per-use licence, the source request's `license_id` is set,
        which moves the amount from the licensee's `reserved_spend_cents` into its
        `committed_spend_cents` in the same request."

        Design: Corner/consistency_model/cascade_results_are_final_in_the_writes_own_response
        """
        ground = _accepted_film_deal(api)
        assert_credit_exposure(
            read_licensee(api, ground["licensee"]["id"]), 0, 1254000, 88746000
        )

        licence = assert_created(
            api.create_license(
                build.per_use_license_payload(
                    ground["request"]["id"],
                    composition_version(api, ground["work"].composition_id),
                ),
                LICENSING_AGENT,
            )
        )
        assert_status(licence, "ISSUED")
        assert_cents_equal(licence["final_fee_cents"], 1254000, "final_fee_cents")
        assert_cents_equal(
            licence["composer_sync_share_cents"], 501600, "composer_sync_share_cents"
        )

        assert_credit_exposure(
            read_licensee(api, ground["licensee"]["id"]), 1254000, 0, 88746000
        )
        request = assert_ok(api.get_sync_request(ground["request"]["id"], LICENSING_AGENT))
        assert request["license_id"] == licence["id"]
        assert_status(request, "ACCEPTED")

    def test_every_touched_row_is_already_recomputed_on_the_very_next_read(self, api):
        """PRD §2.11: "Whenever an event changes an input to a derived field, the service
        recomputes that field in the same request, in a defined order, and every row it
        touches has its `updated_at` refreshed and its `version` incremented."

        Design: Corner/consistency_model/cascade_results_are_final_in_the_writes_own_response
        """
        ground = _accepted_film_deal(api)

        licence = assert_created(
            api.create_license(
                build.per_use_license_payload(
                    ground["request"]["id"],
                    composition_version(api, ground["work"].composition_id),
                ),
                LICENSING_AGENT,
            )
        )

        composition = read_composition(api, ground["work"].composition_id)
        assert composition["active_license_count"] == 1
        assert composition["version"] == 3

        entries = ledger_entries(api, ground["work"].composer_id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["source_type"] == "SYNC_FEE"
        assert entry["source_ref_id"] == licence["id"]
        assert_cents_equal(entry["amount_cents"], 501600, "SYNC_FEE amount_cents")
        assert_same_instant(entry["accrual_recognized_at"], CLOCK_ORIGIN)
        assert entry["cash_recognized_at"] is None

    def test_a_later_clock_advance_neither_reruns_nor_drifts_the_applied_cascade(self, api):
        """PRD §2.11: "Derived fields are never client-supplied and never drift."

        Design: Corner/consistency_model/cascade_results_are_final_in_the_writes_own_response
        """
        ground = _accepted_film_deal(api)
        assert_created(
            api.create_license(
                build.per_use_license_payload(
                    ground["request"]["id"],
                    composition_version(api, ground["work"].composition_id),
                ),
                LICENSING_AGENT,
            )
        )
        licensee_before = read_licensee(api, ground["licensee"]["id"])
        composition_before = read_composition(api, ground["work"].composition_id)

        assert_ok(api.set_clock("2026-08-02T00:00:00Z", ACCOUNTANT_ONE))

        assert read_licensee(api, ground["licensee"]["id"]) == licensee_before
        assert read_composition(api, ground["work"].composition_id) == composition_before
