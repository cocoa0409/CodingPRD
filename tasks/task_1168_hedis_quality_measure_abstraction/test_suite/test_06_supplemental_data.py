"""Supplemental data: batch intake, screening variants, acceptance cascades, and
the ordering of the acceptance precondition checks.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    compute_rate,
    create_active_spec,
    create_and_open_season,
    create_record_payload,
    create_run,
    identify_population,
    list_batch_records,
    list_run_entries,
    list_run_gaps,
    get_provider,
    get_run,
    register_enrolled_member,
    register_provider,
    setup_batch_with_records,
    setup_screened_batch,
    setup_populated_run,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["quality_analyst_headers"]
RELATIONS = TEST_USERS["provider_relations_headers"]


def _two_spec_screening_scenario(api):
    """Season with two ACTIVE ADMINISTRATIVE specs differing only in matching
    policy; members M777 and 4001; one run per spec (denominator 2); each run holds
    one batch with the same two formatting-noisy records."""
    season = create_and_open_season(api, approved_supplemental_sources=["LAB_FEED"])
    spec_ex = create_active_spec(
        api, season["id"], hedis_measure_code="SCR-EX", matching_policy="EXACT"
    )
    spec_to = create_active_spec(
        api, season["id"], hedis_measure_code="SCR-TO", matching_policy="TOLERANT"
    )
    register_enrolled_member(api, "M777", birth_date="1980-06-15T00:00:00Z", gender="M")
    register_enrolled_member(api, "4001", birth_date="1980-06-15T00:00:00Z", gender="F")
    run_ex = identify_population(api, create_run(api, season["id"], spec_ex["id"])["id"])
    run_to = identify_population(api, create_run(api, season["id"], spec_to["id"])["id"])
    assert run_ex["denominator_count"] == 2
    batch_ex, _ = setup_batch_with_records(
        api, run_ex["id"],
        [(" m777 ", "2025-03-05T00:00:00Z", "A1C"),
         ("04001", "2025-04-05T00:00:00Z", "A1C")],
    )
    batch_to, _ = setup_batch_with_records(
        api, run_to["id"],
        [(" m777 ", "2025-03-05T00:00:00Z", "A1C"),
         ("04001", "2025-04-05T00:00:00Z", "A1C")],
    )
    return {"season": season, "run_ex": run_ex, "run_to": run_to,
            "batch_ex": batch_ex, "batch_to": batch_to}


class TestMatchingVariants:
    def test_exact_matching_rejects_formatting_noise(self, api):
        """EXACT string-compares raw member_ref values: ' m777 ' and '04001' match
        no member.

        PRD §3.6: "First, member matching: under the `EXACT` variant the record's
        `member_ref` must string-equal some member's `member_ref` exactly as supplied
        — case, whitespace, and zero-padding differences all reject — while under the
        `TOLERANT` variant both sides are normalized by trimming surrounding
        whitespace and uppercasing, and when the normalized result is entirely digits
        its leading zeros are stripped, an empty remainder counting as the single
        character \"0\"; a record matching no member takes disposition
        `REJECTED_UNKNOWN_MEMBER`."
        PRD §3.6: "The batch's `matching_policy_used` is copied at screen time from
        the run's pinned specification — screening always reflects the spec version
        the run pinned, never a later spec edit."

        Design: Difficulty/dual_variant_calc/supplemental_exact_vs_tolerant_matching
        """
        scenario = _two_spec_screening_scenario(api)
        screened = validate_success(api.screen_batch(scenario["batch_ex"]["id"], ANALYST))
        assert screened["matching_policy_used"] == "EXACT"
        assert screened["accepted_record_count"] == 0, (
            "raw refs ' m777 ' / '04001' do not string-equal 'M777' / '4001'"
        )
        records, _ = list_batch_records(api, scenario["batch_ex"]["id"])
        assert [r["disposition"] for r in records] == [
            "REJECTED_UNKNOWN_MEMBER", "REJECTED_UNKNOWN_MEMBER",
        ]

    def test_tolerant_matching_normalizes_refs(self, api):
        """TOLERANT normalizes case, whitespace, and leading zeros of digit-only
        refs: identical payloads are accepted where EXACT rejected them.

        PRD §3.6: "under the `TOLERANT` variant both sides are normalized by trimming
        surrounding whitespace and uppercasing, and when the normalized result is
        entirely digits its leading zeros are stripped, an empty remainder counting as
        the single character \"0\""
        PRD §3.6: "The variant choice is material: with formatting noise in the source
        references, identical record payloads yield a strictly larger
        `accepted_record_count` under `TOLERANT` than under `EXACT`."

        Design: Difficulty/dual_variant_calc/supplemental_exact_vs_tolerant_matching
        """
        scenario = _two_spec_screening_scenario(api)
        screened = validate_success(api.screen_batch(scenario["batch_to"]["id"], ANALYST))
        assert screened["matching_policy_used"] == "TOLERANT"
        assert screened["accepted_record_count"] == 2, (
            "normalize(' m777 ') == 'M777' and normalize('04001') == '4001'"
        )
        records, _ = list_batch_records(api, scenario["batch_to"]["id"])
        assert [r["disposition"] for r in records] == ["ACCEPTED", "ACCEPTED"]
        screened_ex = validate_success(api.screen_batch(scenario["batch_ex"]["id"], ANALYST))
        assert screened["accepted_record_count"] > screened_ex["accepted_record_count"]


def _gap_cascade_scenario(api):
    """ADMIN run with three attributed members, computed (three OPEN gaps), the
    second gap advanced to OUTREACH_DONE, and a screened LAB_FEED batch holding
    in-window evidence for M1 and M2."""
    season = create_and_open_season(api, approved_supplemental_sources=["LAB_FEED"])
    spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
    p1 = register_provider(api, "P1")
    p2 = register_provider(api, "P2")
    register_enrolled_member(api, "M1", provider_ref="P1", gender="M")
    register_enrolled_member(api, "M2", provider_ref="P1", gender="M")
    register_enrolled_member(api, "M3", provider_ref="P2", gender="F")
    run = identify_population(api, create_run(api, season["id"], spec["id"])["id"])
    assert run["denominator_count"] == 3
    run = compute_rate(api, run["id"])
    gaps, _ = list_run_gaps(api, run["id"])
    assert [g["member_ref"] for g in gaps] == ["M1", "M2", "M3"], (
        "gap list mints in member_ref ascending order"
    )
    assert get_provider(api, p1["id"])["open_gap_count"] == 2
    validate_success(api.mark_gap_outreach_done(gaps[1]["id"], RELATIONS))
    batch, _records, screened = setup_screened_batch(
        api, run["id"],
        [("M1", "2025-05-05T00:00:00Z", "A1C"), ("M2", "2025-05-06T00:00:00Z", "A1C")],
    )
    assert screened["accepted_record_count"] == 2
    return {"season": season, "spec": spec, "run": run, "gaps": gaps, "batch": batch,
            "p1": p1, "p2": p2}


class TestAcceptCascade:
    def test_accept_flips_admin_compliant_and_recomputes_numerator(self, api):
        """Cascade link 1: each ACCEPTED record flips its matching population
        entry's admin_compliant; the run's admin numerator is recomputed.

        PRD §3.6: "On success a three-link cascade fires: each `ACCEPTED` record flips
        its matching population entry's `admin_compliant` to true; each entry so
        flipped auto-closes that member's gap item in `OPEN` or `OUTREACH_DONE`
        status, moving it to `CLOSED_COMPLIANT` with `closure_source` `AUTO_EVIDENCE`;
        and the affected providers' `open_gap_count` is reconciled downward for each
        auto-closed gap."
        PRD §3.7: "The `admin_numerator_count` is the number of non-excluded
        population entries with `admin_compliant` true"

        Design: Difficulty/transitive_cascade/supplemental_accept_numerator_gap_cascade
        """
        scenario = _gap_cascade_scenario(api)
        accepted = validate_success(api.accept_batch(scenario["batch"]["id"], ANALYST))
        assert accepted["status"] == "ACCEPTED"
        entries, _ = list_run_entries(api, scenario["run"]["id"])
        assert [e["admin_compliant"] for e in entries] == [True, True, False], (
            "accepted records flip exactly the matching members' entries"
        )
        run_after = get_run(api, scenario["run"]["id"])
        assert run_after["admin_numerator_count"] == 2

    def test_accept_auto_closes_gaps_and_reconciles_provider_counters(self, api):
        """Cascade links 2 and 3: flipped entries auto-close their OPEN or
        OUTREACH_DONE gaps with AUTO_EVIDENCE, and the provider open-gap counters
        are reconciled downward.

        PRD §3.6: "each entry so flipped auto-closes that member's gap item in `OPEN`
        or `OUTREACH_DONE` status, moving it to `CLOSED_COMPLIANT` with
        `closure_source` `AUTO_EVIDENCE`; and the affected providers' `open_gap_count`
        is reconciled downward for each auto-closed gap."
        PRD §3.7: "A provider's `open_gap_count` at any moment is exactly that
        provider's gap items in `OPEN` or `OUTREACH_DONE`."

        Design: Difficulty/transitive_cascade/supplemental_accept_numerator_gap_cascade
        """
        scenario = _gap_cascade_scenario(api)
        validate_success(api.accept_batch(scenario["batch"]["id"], ANALYST))
        gaps_after, _ = list_run_gaps(api, scenario["run"]["id"])
        assert [g["status"] for g in gaps_after] == [
            "CLOSED_COMPLIANT", "CLOSED_COMPLIANT", "OPEN",
        ], "M1/M2 gaps auto-close on evidence; M3 received none"
        assert gaps_after[0]["closure_source"] == "AUTO_EVIDENCE"
        assert gaps_after[1]["closure_source"] == "AUTO_EVIDENCE", (
            "auto-close also fires from OUTREACH_DONE"
        )
        assert gaps_after[2]["closure_source"] is None
        p1_after = get_provider(api, scenario["p1"]["id"])
        p2_after = get_provider(api, scenario["p2"]["id"])
        assert p1_after["open_gap_count"] == 0, (
            f"P1's two gaps were both auto-closed; got {p1_after['open_gap_count']}"
        )
        assert p2_after["open_gap_count"] == 1


def _accept_priority_scenario(api):
    """One ADMIN run with denominator 1 (only M1), plus two screened batches each
    holding one record for the unknown member M999: batch_badsrc from PHARMACY (not
    in the season registry), batch_ref from LAB_FEED (approved)."""
    season = create_and_open_season(api, approved_supplemental_sources=["LAB_FEED"])
    spec = create_active_spec(api, season["id"], hedis_measure_code="SCR1")
    register_enrolled_member(api, "M1", gender="F")
    run = identify_population(api, create_run(api, season["id"], spec["id"])["id"])
    assert run["denominator_count"] == 1
    bad_src, _r, _s = setup_screened_batch(
        api, run["id"], [("M999", "2025-05-05T00:00:00Z", "A1C")], source_type="PHARMACY"
    )
    ref_src, _r2, _s2 = setup_screened_batch(
        api, run["id"], [("M999", "2025-05-05T00:00:00Z", "A1C")], source_type="LAB_FEED"
    )
    return {"run": run, "batch_badsrc": bad_src, "batch_ref": ref_src}


class TestAcceptPreconditionOrdering:
    def test_unapproved_source_masks_record_referential(self, api):
        """When both the source-approval check and the per-record denominator check
        would fail, the source-approval error is reported.

        PRD §3.6: "the batch's `source_type` must appear in the season's
        `approved_supplemental_sources` registry (else
        `ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE`); and every record of the batch must
        reference a `member_ref` present among the run's non-excluded population
        entries (else `ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR`) — the source-approval
        check is evaluated strictly before the per-record denominator check, per
        §2.9."

        Design: Difficulty/priority_pair_validation_conflict/accept_source_safety_beats_record_referential
        """
        scenario = _accept_priority_scenario(api)
        resp = api.accept_batch(scenario["batch_badsrc"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE)

    def test_approved_source_surfaces_record_referential(self, api):
        """With the source approved, the per-record denominator check fires: M999 is
        not among the run's non-excluded population entries.

        PRD §3.6: "every record of the batch must reference a `member_ref` present
        among the run's non-excluded population entries (else
        `ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR`) — the source-approval check is
        evaluated strictly before the per-record denominator check, per §2.9."
        PRD §2.9: "On supplemental batch acceptance, every record must reference a
        member of the run's non-excluded population, else
        `ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR` (HTTP 422) — checked strictly after the
        source-approval check of band 8."

        Design: Difficulty/priority_pair_validation_conflict/accept_source_safety_beats_record_referential
        """
        scenario = _accept_priority_scenario(api)
        resp = api.accept_batch(scenario["batch_ref"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR)


class TestBatchRejectPath:
    def test_batch_reject_path_has_no_numerator_effect(self, api):
        """Rejecting a screened batch applies no numerator or compliance effects.

        PRD §3.6: "Rejection moves a screened batch to `REJECTED`. It carries no
        numerator or gap effects at all — only the batch's `version` increments — and
        `REJECTED` is terminal alongside `ACCEPTED`."

        Design: Corner/state_machines/batch_reject_path_has_no_numerator_effect
        """
        scenario = setup_populated_run(api, member_refs=("M1",))
        batch, _records, screened = setup_screened_batch(
            api, scenario["run"]["id"], [("M1", "2025-05-05T00:00:00Z", "A1C")]
        )
        assert screened["accepted_record_count"] == 1
        rejected = validate_success(api.reject_batch(batch["id"], ANALYST))
        assert rejected["status"] == "REJECTED"
        run_after = get_run(api, scenario["run"]["id"])
        assert run_after["admin_numerator_count"] == 0
        entries, _ = list_run_entries(api, scenario["run"]["id"])
        assert entries[0]["admin_compliant"] is False


class TestScreeningDispositions:
    def test_supplemental_window_and_cross_batch_duplicate_dispositions(self, api):
        """Screening is per-record: a duplicate of an already-ACCEPTED record of
        another batch of the same run is REJECTED_DUPLICATE; a prior-year service
        date is REJECTED_OUT_OF_WINDOW.

        PRD §3.6: "Second, the service window: the record's `service_date`, at
        whole-day granularity, must fall within the calendar year of the season's
        `measurement_year` — from January 1 through December 31 of that year, both
        inclusive — else the record takes `REJECTED_OUT_OF_WINDOW`. Third,
        duplication: a record whose normalized triple of `member_ref`, the date part
        of `service_date`, and `evidence_code` equals that of a record earlier in this
        batch's processing order, or of a record already `ACCEPTED` in another
        accepted batch of the same run, takes `REJECTED_DUPLICATE`; cross-batch
        duplicates surface only here as per-record dispositions, never as request
        failures."

        Design: Corner/calculations/supplemental_window_and_cross_batch_duplicate_dispositions
        """
        season = create_and_open_season(
            api, approved_supplemental_sources=["LAB_FEED", "IMMUNIZATION_REGISTRY"]
        )
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        register_enrolled_member(api, "M1", gender="F")
        run = identify_population(api, create_run(api, season["id"], spec["id"])["id"])
        batch1, _r, accepted1 = _screen_and_accept(
            api, run["id"], [("M1", "2025-06-01T00:00:00Z", "A1C")], "LAB_FEED"
        )
        assert accepted1["status"] == "ACCEPTED"
        batch2, _rows = setup_batch_with_records(
            api, run["id"],
            [("M1", "2025-06-01T00:00:00Z", "A1C"),
             ("M1", "2024-12-31T00:00:00Z", "A1C")],
            source_type="IMMUNIZATION_REGISTRY",
        )
        screened2 = validate_success(api.screen_batch(batch2["id"], ANALYST))
        assert screened2["record_count"] == 2
        assert screened2["accepted_record_count"] == 0
        records, _ = list_batch_records(api, batch2["id"])
        assert records[0]["disposition"] == "REJECTED_DUPLICATE", (
            "X matches the already-ACCEPTED R1 from batch1 (same run, ACCEPTED batch)"
        )
        assert records[1]["disposition"] == "REJECTED_OUT_OF_WINDOW", (
            "2024-12-31 is outside measurement year 2025"
        )


class TestRecordIntake:
    def test_same_batch_duplicate_record_returns_409(self, api):
        """An identical (member_ref, service_date, evidence_code) record already in
        the same batch is rejected at intake.

        PRD §3.6: "One request-level uniqueness rule applies at intake: a record
        identical in `member_ref`, `service_date`, and `evidence_code` to one already
        present in the same batch is rejected outright with
        `ERR_DUPLICATE_SERVICE_DATE`."

        Design: Corner/validations/same_batch_duplicate_record_returns_409
        """
        scenario = setup_populated_run(api, member_refs=("M1",))
        batch, _rows = setup_batch_with_records(
            api, scenario["run"]["id"], [("M1", "2025-06-01T00:00:00Z", "A1C")]
        )
        resp = api.create_supplemental_record(
            create_record_payload(batch["id"], "M1", "2025-06-01T00:00:00Z", "A1C"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERVICE_DATE)

    def test_record_create_on_screened_batch_rejected(self, api):
        """Records may only be added while the batch is RECEIVED.

        PRD §3.6: "Records are added to a batch while — and only while — it is
        `RECEIVED`; adding to a screened or settled batch is `ERR_INVALID_STATE`."

        Design: Corner/validations/record_create_on_screened_batch_rejected
        """
        scenario = setup_populated_run(api, member_refs=("M1",))
        batch, _rows, _screened = setup_screened_batch(
            api, scenario["run"]["id"], [("M1", "2025-05-05T00:00:00Z", "A1C")]
        )
        resp = api.create_supplemental_record(
            create_record_payload(batch["id"], "M1", "2025-06-06T00:00:00Z", "MAMMO"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _screen_and_accept(api, run_id, records, source_type):
    batch, rows, _screened = setup_screened_batch(api, run_id, records, source_type)
    accepted = validate_success(api.accept_batch(batch["id"], ANALYST))
    return batch, rows, accepted
