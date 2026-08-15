"""Certification: issuance gates, segregation of duties, the re-issue cycle,
and the correction cascade's terminal hop (certification revocation)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_certification,
    create_correction_payload,
    find_awards,
    finalize_race,
    get_race,
    get_result_for_registration,
    make_certification_officer_headers,
    parse_iso,
    publish_race,
    race_version,
    certify_race,
    setup_divergence_race,
    setup_single_finisher_published_race,
    validate_error,
    validate_paginated,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
OF = TEST_USERS["race_official_headers"]


class TestCertificationGates:
    def test_certification_uncertified_course_rejected(self, api):
        """PRD §3.8: "Certification demands that the race be `FINALIZED`; that
        its `course_type` be `CERTIFIED_COURSE` — an `UNCERTIFIED_COURSE` race
        is refused with `ERR_COURSE_NOT_CERTIFIED`"

        Design: Corner/state_machines/certification_uncertified_course_rejected
        """
        ctx = setup_single_finisher_published_race(
            name="Fun Run 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            finish_ts="2026-08-01T07:20:05.000Z",
            publish_time="2026-08-01T08:30:00Z")
        finalize_race(ctx, "2026-08-01T09:00:00Z")

        resp = api.certify_race(ctx["race"]["id"],
                                make_certification_officer_headers("cert-9"))
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_CERTIFIED,
                       expected_status=422)
        _certs, meta = validate_paginated(
            api.list_race_certifications(ctx["race"]["id"], RD))
        assert meta["total_count"] == 0, "no certification row may be created"

    def test_certification_sod_rejected(self, api):
        """PRD §2.9: "Second, the officer who certifies a finalized race must
        not be the director who locked its timing configuration: certification
        requires the acting `X-User-ID` to differ from the race's
        `locked_by_user_id`."
        PRD §3.8: "The checks run state first, then the duty rule — a collision
        fails with `ERR_SOD_VIOLATION` — then the course requirement."

        Design: Corner/state_machines/certification_sod_rejected
        """
        ctx = setup_single_finisher_published_race(
            name="SoD 5K", distance_km=5.0, cutoff_minutes=90,
            finish_ts="2026-08-01T07:20:05.000Z",
            publish_time="2026-08-01T08:30:00Z", lock_user_id="director-1")
        finalize_race(ctx, "2026-08-01T09:00:00Z")
        assert get_race(ctx)["locked_by_user_id"] == "director-1"

        resp = api.certify_race(ctx["race"]["id"],
                                make_certification_officer_headers("director-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

        cert = validate_success(api.certify_race(
            ctx["race"]["id"], make_certification_officer_headers("cert-2")), 200)
        assert_certification(cert)
        assert cert["status"] == "ISSUED"
        assert cert["issued_by_user_id"] == "cert-2"


class TestCertificationReissueCycle:
    def test_certification_reissue_cycle(self, api):
        """PRD §3.8: "Each race owns exactly one **Certification** row, created
        on first issuance and reused on every re-issuance thereafter."
        PRD §3.8: "Issuance, including re-issuance from `REVOKED`, moves the row
        to `ISSUED`, stamps `issued_at` with the logical now, records
        `issued_by_user_id`, recomputes `qualified_count` as the number of
        results currently carrying `qualified` true, and clears
        `revocation_reason` to null. An approved correction revokes an `ISSUED`
        certification automatically per §3.7, and the race must be re-published,
        re-finalized, and re-certified to restore it."
        PRD §3.6: "a result is marked `qualified` when the race defines
        `qualifying_standard_ms`, the result is not excluded, and its
        `chip_time_ms` is less than or equal to the standard — the boundary is
        inclusive."

        Design: Corner/state_machines/certification_reissue_cycle
        """
        # Finisher's chip time is 1805000 ms: above the 1800000 ms standard.
        ctx = setup_single_finisher_published_race(
            name="Cert Cycle 10K", qualifying_standard_ms=1800000,
            finish_ts="2026-08-01T07:30:10.000Z")
        finalize_race(ctx, "2026-08-01T09:30:00Z")
        cert1 = certify_race(ctx, "cert-1")
        assert cert1["status"] == "ISSUED"
        assert cert1["qualified_count"] == 0, "1805000 exceeds the standard"

        # Adjust the start read 5s later: chip becomes exactly the standard.
        corr = validate_success(api.create_correction(
            create_correction_payload(ctx["race"]["id"],
                                      ctx["reads"]["start_read"]["id"],
                                      "ADJUST_READ_TIME", "start mat late-triggered",
                                      corrected_timestamp="2026-08-01T07:00:10.000Z"),
            OF), 201)
        validate_success(api.adjudicate_correction(
            corr["id"], "APPROVED", race_version(ctx), OF), 200)

        revoked = validate_success(api.list_race_certifications(ctx["race"]["id"], RD), 200)
        assert revoked[0]["status"] == "REVOKED"
        assert revoked[0]["revocation_reason"] == "CORRECTION_APPROVED"

        publish_race(ctx, "2026-08-01T09:30:00Z")
        result = get_result_for_registration(ctx["regs"]["r1"]["id"])
        assert result["chip_time_ms"] == 1800000, "07:30:10 - 07:00:10"
        assert result["qualified"] is True, "equality with the standard qualifies"
        finalize_race(ctx, "2026-08-01T10:07:00Z")

        cert2 = validate_success(api.certify_race(
            ctx["race"]["id"], make_certification_officer_headers("cert-1")), 200)
        assert cert2["id"] == cert1["id"], "the single per-race row is reused"
        assert cert2["status"] == "ISSUED"
        assert cert2["qualified_count"] == 1
        assert cert2["revocation_reason"] is None
        assert cert2["issued_by_user_id"] == "cert-1"


class TestCorrectionCascadeToCertification:
    def _certified_divergence_with_correction(self, api):
        ctx = setup_divergence_race(finalize=True, certify=True, cert_user_id="cert-1")
        assert ctx["certification"]["qualified_count"] == 0
        corr = validate_success(api.create_correction(
            create_correction_payload(ctx["race"]["id"],
                                      ctx["reads"]["b_finish_read"]["id"],
                                      "ADJUST_READ_TIME",
                                      "photo review: B finished later",
                                      corrected_timestamp="2026-08-01T07:44:20.000Z"),
            OF), 201)
        ctx["correction_id"] = corr["id"]
        return ctx

    def test_cascade_rewrites_read_and_amends_results(self, api):
        """PRD §3.7: "First, the read mutates: exclusion moves it `SCORED →
        EXCLUDED`; reinstatement moves it `EXCLUDED → SCORED`; adjustment keeps
        it `SCORED` while rewriting its `read_timestamp` and stamping
        `adjusted_by_correction_id` with the correction's id. Second, the full
        four-phase recompute of §3.6 re-runs, and any `OFFICIAL` result whose
        computed fields change moves to `AMENDED` with its `revision`
        incremented by one."

        Design: Difficulty/transitive_cascade/correction_cascade_to_certification_revocation
        """
        ctx = self._certified_divergence_with_correction(api)
        validate_success(api.adjudicate_correction(
            ctx["correction_id"], "APPROVED", race_version(ctx), OF), 200)

        read = validate_success(api.get_timing_read(
            ctx["reads"]["b_finish_read"]["id"],
            TEST_USERS["timing_operator_headers"]), 200)
        assert parse_iso(read["read_timestamp"]) == parse_iso("2026-08-01T07:44:20.000Z")
        assert read["adjusted_by_correction_id"] == ctx["correction_id"]
        assert read["status"] == "SCORED"

        res_b = get_result_for_registration(ctx["regs"]["b"]["id"])
        assert res_b["status"] == "AMENDED"
        assert res_b["revision"] == 2
        assert res_b["chip_time_ms"] == 2030000  # 1910000 + 120000
        assert res_b["gun_time_ms"] == 2060000   # 1940000 + 120000
        assert res_b["age_group_rank_chip"] == 2, "A's 1920000 now leads the category"

        # A's gun side is untouched, but the age-group rank moved 2 -> 1, so
        # the recompute marks A's row AMENDED as well.
        res_a = get_result_for_registration(ctx["regs"]["a"]["id"])
        assert res_a["overall_rank_gun"] == 1
        assert res_a["age_group_rank_chip"] == 1
        assert res_a["status"] == "AMENDED"
        assert res_a["revision"] == 2

    def test_cascade_swaps_award_reopens_race_and_revokes_certification(self, api):
        """PRD §3.7: "Third, awards swap per §3.6: stale rows are `REVOKED` and
        replacements created `PROJECTED`, with `CONFIRMED` status restored only
        after a subsequent finalization. Fourth, the race itself re-opens,
        moving from `PROVISIONAL_PUBLISHED` or `FINALIZED` into
        `AMENDMENT_OPEN` with `amendment_count` incremented by one, and an
        `ISSUED` certification is automatically `REVOKED` with
        `revocation_reason` set to `CORRECTION_APPROVED`. Finally, the race
        `version` increments by one."

        Design: Difficulty/transitive_cascade/correction_cascade_to_certification_revocation
        """
        ctx = self._certified_divergence_with_correction(api)
        race_id = ctx["race"]["id"]
        validate_success(api.adjudicate_correction(
            ctx["correction_id"], "APPROVED", race_version(ctx), OF), 200)

        revoked = find_awards(race_id, "AG_M_35_39", place=1, status="REVOKED")
        assert len(revoked) == 1
        assert revoked[0]["registration_id"] == ctx["regs"]["b"]["id"]
        projected = find_awards(race_id, "AG_M_35_39", place=1, status="PROJECTED")
        assert len(projected) == 1
        assert projected[0]["registration_id"] == ctx["regs"]["a"]["id"]
        assert projected[0]["basis_time_ms"] == 1920000

        race = get_race(ctx)
        assert race["status"] == "AMENDMENT_OPEN"
        assert race["amendment_count"] == 1

        certs = validate_success(api.list_race_certifications(race_id, RD), 200)
        assert certs[0]["status"] == "REVOKED"
        assert certs[0]["revocation_reason"] == "CORRECTION_APPROVED"
