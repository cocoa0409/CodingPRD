"""MARPOL notes, retained-sample custody and the gates in front of a claim.

The note carries two independent global uniqueness constraints and supersedes its
predecessor when a corrected one is issued. Everything downstream of it is clock
driven: the sample's custody status is derived on every read rather than stored, a
claim has thirty days to be raised, and the laboratory may not touch a sample that
has not been released to it.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    LAB,
    OPS,
    SURVEYOR,
    api_client,
    assert_bunker_delivery_note,
    build_delivered_order,
    build_issued_bdn,
    claim_decision_payload,
    create_bdn_payload,
    create_lab_analysis_payload,
    create_quality_claim_payload,
    file_lab_analysis,
    issue_bdn,
    make_customer_rep_headers,
    raise_claim,
    raise_invoice,
    read_bdn,
    read_claim,
    release_sample,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_BDN_NUMBER = "BDN-2026-0002"
SECOND_SEAL_NUMBER = "SEAL-0002"
CORRECTED_SULFUR_PCT = 0.099

RETENTION_UNTIL = "2026-11-08T14:30:00"
PAST_THE_CLAIM_WINDOW = "2026-09-15T14:30:00Z"
PAST_THE_RETENTION = "2026-11-09T14:30:00Z"

OVERSIZED_CLAIM_MT = 2000.000
CLAIMED_MT = 400.000

OFF_SPEC_SULFUR_PCT = 0.135
ON_SPEC_SULFUR_PCT = 0.104
SECOND_LAB_REF = "LAB-0002"


class TestNoteNumberAndSealUniqueness:
    """Two independent uniqueness constraints, then supersession."""

    def test_a_corrected_note_must_clear_both_constraints_before_it_supersedes(self):
        """PRD §3.7: "Both `bdn_number` and `sample_seal_number` are unique across all
        notes, and collisions are rejected with `ERR_DUPLICATE_BDN_NUMBER` and
        `ERR_DUPLICATE_SAMPLE_SEAL` respectively (both HTTP 409)."
        PRD §3.7: "Issuing a corrected note against the same delivery order supersedes
        the earlier one: the prior note transitions `ISSUED → SUPERSEDED`, provided no
        quality claim references it, and a superseded note stops backing claims — only the
        note in `ISSUED` status may be claimed against."
        PRD §3.7: "A newly issued note snapshots `delivered_quantity_mt` from the order's
        `agreed_quantity_mt` at the moment of issuance, sets `status` to `ISSUED`, and
        starts the sample custody clock: `sample_retention_until` is the note's
        `created_at` plus a 90-day retention period, `sample_custody_status` begins as
        `RETAINED`, and `sample_released_at` is null."

        Both constraints are global rather than per-order, so they bite even on a
        correction to the very order that already holds the colliding note. Only the
        attempt that collides on neither is created, and only then does the first note
        step aside.

        Design: Corner/validations/duplicate_bdn_number_and_sample_seal_rejected
        """
        ctx = build_issued_bdn()
        first = ctx["bdn"]
        assert first["status"] == "ISSUED", (
            f"The first note must be issued, got {first['status']}"
        )

        duplicate_number = api_client.create_bunker_delivery_note(
            create_bdn_payload(
                ctx["order"]["id"],
                bdn_number=first["bdn_number"],
                declared_sulfur_pct=CORRECTED_SULFUR_PCT,
                sample_seal_number=SECOND_SEAL_NUMBER,
            ),
            OPS,
        )
        validate_error(duplicate_number, ApiErrorId.ERR_DUPLICATE_BDN_NUMBER)

        duplicate_seal = api_client.create_bunker_delivery_note(
            create_bdn_payload(
                ctx["order"]["id"],
                bdn_number=SECOND_BDN_NUMBER,
                declared_sulfur_pct=CORRECTED_SULFUR_PCT,
                sample_seal_number=first["sample_seal_number"],
            ),
            OPS,
        )
        validate_error(duplicate_seal, ApiErrorId.ERR_DUPLICATE_SAMPLE_SEAL)
        assert read_bdn(ctx, bdn_id=first["id"])["status"] == "ISSUED", (
            "Neither refusal may supersede the standing note"
        )

        corrected = validate_success(
            api_client.create_bunker_delivery_note(
                create_bdn_payload(
                    ctx["order"]["id"],
                    bdn_number=SECOND_BDN_NUMBER,
                    declared_sulfur_pct=CORRECTED_SULFUR_PCT,
                    sample_seal_number=SECOND_SEAL_NUMBER,
                ),
                OPS,
            ),
            201,
        )

        assert_bunker_delivery_note(corrected)
        assert corrected["status"] == "ISSUED", (
            f"The corrected note opens ISSUED, got {corrected['status']}"
        )
        assert corrected["delivered_quantity_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The corrected note snapshots the settled tonnage too, got "
            f"{corrected['delivered_quantity_mt']}"
        )
        assert corrected["sample_custody_status"] == "RETAINED", (
            f"A fresh seal starts retained, got {corrected['sample_custody_status']}"
        )
        assert corrected["sample_retention_until"].startswith(RETENTION_UNTIL), (
            "90 days after 2026-08-10T14:30:00Z is 2026-11-08T14:30:00Z, got "
            f"{corrected['sample_retention_until']}"
        )
        assert read_bdn(ctx, bdn_id=first["id"])["status"] == "SUPERSEDED", (
            "The predecessor must step aside, got "
            f"{read_bdn(ctx, bdn_id=first['id'])['status']}"
        )
        notes, meta = validate_paginated(
            api_client.list_bunker_delivery_notes(
                OPS, params={"delivery_order_id": ctx["order"]["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            "The two refused attempts must have persisted nothing, got "
            f"{meta['total_count']} notes on the order"
        )
        assert {note["bdn_number"] for note in notes} == {
            first["bdn_number"], SECOND_BDN_NUMBER
        }, (
            "Only the two created notes may exist, got "
            f"{[note['bdn_number'] for note in notes]}"
        )


class TestClaimBasisAndClockWindows:
    """One note, three refusals driven by its basis and its clocks."""

    def test_a_claim_larger_than_the_note_basis_is_refused(self):
        """PRD §3.7: "And `affected_quantity_mt` may not exceed the note's
        `delivered_quantity_mt`, or the claim is rejected with
        `ERR_AFFECTED_QUANTITY_EXCEEDS_BASIS` (HTTP 422)."
        PRD §3.7: "On submission the claim snapshots `quantity_basis_mt` from the note's
        `delivered_quantity_mt` and copies `customer_id` from the nomination behind the
        note; that snapshot is taken once and never re-read, so a later corrected note
        cannot retroactively move the basis of a claim already in flight."

        The buyer cannot claim 2000.000 tonnes were unusable when only 1198.450 were
        delivered.

        Design: Corner/validations/claim_basis_and_retention_windows_rejected
        """
        ctx = build_issued_bdn()
        assert ctx["bdn"]["delivered_quantity_mt"] == pytest.approx(
            1198.450, abs=0.0005
        ), (
            "The note must carry the settled tonnage, got "
            f"{ctx['bdn']['delivered_quantity_mt']}"
        )

        response = api_client.create_quality_claim(
            create_quality_claim_payload(
                ctx["bdn"]["id"], affected_quantity_mt=OVERSIZED_CLAIM_MT
            ),
            make_customer_rep_headers(ctx["customer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_AFFECTED_QUANTITY_EXCEEDS_BASIS)
        _, meta = validate_paginated(
            api_client.list_quality_claims(
                SURVEYOR, params={"bdn_id": ctx["bdn"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"The refused claim must not exist, got {meta['total_count']} claims"
        )

    def test_a_claim_raised_after_thirty_days_is_refused(self):
        """PRD §3.7: "The claim must be raised inside a 30-day window: the logical clock
        must be no later than the note's `created_at` plus 30 days, or the claim is
        rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422)."
        PRD §2.4: "Every subsequent evaluation of sample custody, claim windows, notice
        periods, slot admissibility and spill-decay ageing uses the new instant."

        The note was created at 2026-08-10T14:30:00Z, so the window closed at
        2026-09-09T14:30:00Z and a claim on 2026-09-15 is six days too late.

        Design: Corner/validations/claim_basis_and_retention_windows_rejected
        """
        ctx = build_issued_bdn()
        set_logical_clock(PAST_THE_CLAIM_WINDOW)

        response = api_client.create_quality_claim(
            create_quality_claim_payload(
                ctx["bdn"]["id"], affected_quantity_mt=CLAIMED_MT
            ),
            make_customer_rep_headers(ctx["customer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED)
        _, meta = validate_paginated(
            api_client.list_quality_claims(
                SURVEYOR, params={"bdn_id": ctx["bdn"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"The refused claim must not exist, got {meta['total_count']} claims"
        )

    def test_a_sample_released_after_its_retention_lapses_is_refused(self):
        """PRD §3.7: "A release attempted after the retention period has lapsed — that
        is, when the logical clock is past `sample_retention_until`, so custody already
        reads `EXPIRED` — is rejected with `ERR_SAMPLE_RETENTION_EXPIRED` (HTTP 422),
        because a sample outside its retention window can no longer back a claim."
        PRD §3.7: "Sample custody is derived on every read rather than stored as an
        independent fact. If `sample_released_at` is set, `sample_custody_status` reads
        `RELEASED_TO_LAB`; otherwise, if the logical clock is past
        `sample_retention_until`, it reads `EXPIRED`; otherwise it reads `RETAINED`."

        Retention ran out at 2026-11-08T14:30:00Z, so at 2026-11-09T14:30:00Z the read
        already says `EXPIRED` and the release has nothing left to release.

        Design: Corner/validations/claim_basis_and_retention_windows_rejected
        """
        ctx = build_issued_bdn()
        assert ctx["bdn"]["sample_custody_status"] == "RETAINED", (
            f"The sample starts retained, got {ctx['bdn']['sample_custody_status']}"
        )
        set_logical_clock(PAST_THE_RETENTION)

        response = api_client.release_sample(ctx["bdn"]["id"], OPS)

        validate_error(response, ApiErrorId.ERR_SAMPLE_RETENTION_EXPIRED)
        note = read_bdn(ctx)
        assert note["sample_released_at"] is None, (
            f"The refused release must stamp nothing, got {note['sample_released_at']}"
        )
        assert note["sample_custody_status"] == "EXPIRED", (
            "Custody must be re-derived against the moved clock, got "
            f"{note['sample_custody_status']}"
        )
        assert note["sample_retention_until"].startswith(RETENTION_UNTIL), (
            "The retention instant itself must not move, got "
            f"{note['sample_retention_until']}"
        )
        assert note["status"] == "ISSUED", (
            f"An expired sample does not unissue the note, got {note['status']}"
        )


class TestAnalysisPipelineGates:
    """A decision cannot precede the analysis, and the analysis cannot precede the
    release of the sample."""

    def test_the_gates_open_in_order_and_the_verdict_lands_on_the_trip_point(self):
        """PRD §3.8: "Filing is only possible once the note's `sample_custody_status` is
        `RELEASED_TO_LAB`; a claim whose sample is still retained or already expired is
        rejected with `ERR_SAMPLE_NOT_RELEASED` (HTTP 409)."
        PRD §3.8: "The first filing on a claim moves it `SUBMITTED → UNDER_ANALYSIS`,
        sets the analysis's `round_index` to 1 and the claim's `analysis_round` to 1, and
        increments the claim's `version` by one."
        PRD §3.8: "A filing against a claim in any other status is rejected with
        `ERR_INVALID_CLAIM_STATE` (HTTP 409)."
        PRD §3.8: "The trip point is the effective limit plus the grade's
        `test_tolerance_pct`, the ISO 4259 reproducibility allowance."
        PRD §3.8: "`exceedance_pct` is `measured_sulfur_pct` minus the trip point,
        rounded to three decimal places, and floored at 0.000, so an on-spec result always
        reports an exceedance of 0.000."
        PRD §2.8: "And the quality claim's `status` legality check guards four operations
        with `ERR_INVALID_CLAIM_STATE`: filing a laboratory analysis, submitting a
        surveyor decision, requesting a retest, and accepting a remediation."

        A provisional invoice stands on the order, so the surveyor's decision is refused
        on the claim's own status rather than on a missing invoice. The scrubberless
        vessel took the stem into an emission-control port whose limit is 0.100 and the
        grade allows a 0.010 reproducibility tolerance, so the trip point is 0.110 and a
        measurement of 0.135 exceeds it by 0.025.

        Design: Corner/validations/lab_analysis_and_decision_preconditions_rejected
        """
        ctx = build_delivered_order()
        issue_bdn(ctx)
        raise_invoice(ctx)
        claim = raise_claim(ctx)
        assert claim["status"] == "SUBMITTED", (
            f"A fresh claim opens SUBMITTED, got {claim['status']}"
        )
        assert claim["analysis_round"] == 0, (
            f"No round has been run yet, got {claim['analysis_round']}"
        )

        premature_decision = api_client.claim_decision(
            claim["id"], claim_decision_payload("PROPOSE"), SURVEYOR
        )
        validate_error(premature_decision, ApiErrorId.ERR_INVALID_CLAIM_STATE)

        retained_sample = api_client.create_lab_analysis(
            create_lab_analysis_payload(
                claim["id"],
                claim["version"],
                measured_sulfur_pct=OFF_SPEC_SULFUR_PCT,
            ),
            LAB,
        )
        validate_error(retained_sample, ApiErrorId.ERR_SAMPLE_NOT_RELEASED)
        unchanged = read_claim(ctx)
        assert unchanged["version"] == claim["version"], (
            f"A refused filing must not move the version, expected "
            f"{claim['version']}, got {unchanged['version']}"
        )
        assert unchanged["status"] == "SUBMITTED", (
            f"The claim must stay submitted, got {unchanged['status']}"
        )
        note = release_sample(ctx)
        assert note["sample_custody_status"] == "RELEASED_TO_LAB", (
            f"The release must flip custody, got {note['sample_custody_status']}"
        )

        analysis = validate_success(
            api_client.create_lab_analysis(
                create_lab_analysis_payload(
                    claim["id"],
                    claim["version"],
                    measured_sulfur_pct=OFF_SPEC_SULFUR_PCT,
                ),
                LAB,
            ),
            201,
        )

        assert analysis["verdict"] == "OFF_SPEC", (
            f"0.135 is above the 0.110 trip point, got {analysis['verdict']}"
        )
        assert analysis["exceedance_pct"] == pytest.approx(0.025, abs=0.0005), (
            f"0.135 less the 0.110 trip point is 0.025, got "
            f"{analysis['exceedance_pct']}"
        )
        assert analysis["round_index"] == 1, (
            f"This is the first round, got {analysis['round_index']}"
        )
        assert analysis["retest_of_analysis_id"] is None, (
            "A first round names no predecessor, got "
            f"{analysis['retest_of_analysis_id']}"
        )
        after = read_claim(ctx)
        assert after["status"] == "UNDER_ANALYSIS", (
            f"The filing must move the claim, got {after['status']}"
        )
        assert after["analysis_round"] == 1, (
            f"The claim must count the round, got {after['analysis_round']}"
        )
        assert after["version"] == claim["version"] + 1, (
            f"The filing increments the version once, expected "
            f"{claim['version'] + 1}, got {after['version']}"
        )


class TestStaleClaimVersionOnAnalysis:
    """The retest guard refuses a filing made from a read that predates round one."""

    def test_a_second_filing_carrying_the_original_version_is_refused(self):
        """PRD §2.9: "Filing a laboratory analysis against a quality claim requires the
        non-optional input field `expected_claim_version`, carrying the client's last
        observed `version` of the target `QualityClaim`. A mismatch with the claim's
        current `version` is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."
        PRD §2.9: "A retest round legitimately supersedes the previous round's verdict as
        the basis for the remediation decision, so a filing made from a stale read would
        otherwise overwrite a governing verdict the requester had not read."
        PRD §3.8: "A second filing is a self-loop that re-enters `UNDER_ANALYSIS`: it
        requires the claim to be in `UNDER_ANALYSIS`, requires `analysis_round` to still
        be below the ceiling of two rounds, and requires `retest_of_analysis_id` to
        reference an analysis on this same claim whose `round_index` is 1. It sets the new
        analysis's `round_index` to 2 and the claim's `analysis_round` to 2 and increments
        the claim's `version` by one."
        PRD §3.8: "The `verdict` is `OFF_SPEC` when `measured_sulfur_pct` is strictly
        greater than that trip point and `ON_SPEC` otherwise — a measurement exactly equal
        to the trip point is `ON_SPEC`."

        The first round already bumped the claim, so the second filing quoting the
        submission-time version is refused and nothing about round one moves. Refetching
        the claim and quoting what it now says lets the same filing through, and the
        0.104 result sits under the 0.110 trip point.

        Design: Corner/cross_cutting_complexity_layers/stale_claim_version_on_lab_analysis_rejected
        """
        ctx = build_delivered_order()
        issue_bdn(ctx)
        release_sample(ctx)
        claim = raise_claim(ctx)
        submitted_version = claim["version"]
        first_round = file_lab_analysis(
            ctx, measured_sulfur_pct=OFF_SPEC_SULFUR_PCT
        )
        assert first_round["round_index"] == 1, (
            f"The setup must have filed round one, got {first_round['round_index']}"
        )

        stale = api_client.create_lab_analysis(
            create_lab_analysis_payload(
                claim["id"],
                submitted_version,
                lab_ref=SECOND_LAB_REF,
                measured_sulfur_pct=ON_SPEC_SULFUR_PCT,
                retest_of_analysis_id=first_round["id"],
            ),
            LAB,
        )

        validate_error(stale, ApiErrorId.ERR_STALE_CLAIM_VERSION)
        _, meta = validate_paginated(
            api_client.list_lab_analyses(LAB, params={"claim_id": claim["id"]})
        )
        assert meta["total_count"] == 1, (
            f"The refused filing must not exist, got {meta['total_count']} analyses"
        )
        current = read_claim(ctx)
        assert current["analysis_round"] == 1, (
            f"The round counter must not move, got {current['analysis_round']}"
        )
        assert current["version"] == submitted_version + 1, (
            f"Only the first round moved the version, expected "
            f"{submitted_version + 1}, got {current['version']}"
        )

        retest = validate_success(
            api_client.create_lab_analysis(
                create_lab_analysis_payload(
                    claim["id"],
                    current["version"],
                    lab_ref=SECOND_LAB_REF,
                    measured_sulfur_pct=ON_SPEC_SULFUR_PCT,
                    retest_of_analysis_id=first_round["id"],
                ),
                LAB,
            ),
            201,
        )

        assert retest["round_index"] == 2, (
            f"The accepted filing is round two, got {retest['round_index']}"
        )
        assert retest["verdict"] == "ON_SPEC", (
            f"0.104 is below the 0.110 trip point, got {retest['verdict']}"
        )
        assert retest["exceedance_pct"] == pytest.approx(0.000, abs=0.0005), (
            f"An on-spec result reports no exceedance, got {retest['exceedance_pct']}"
        )
        assert retest["retest_of_analysis_id"] == first_round["id"], (
            "The retest must name the round it re-examines, got "
            f"{retest['retest_of_analysis_id']}"
        )
        final = read_claim(ctx)
        assert final["analysis_round"] == 2, (
            f"The claim must count the second round, got {final['analysis_round']}"
        )
        assert final["version"] == current["version"] + 1, (
            f"The accepted filing increments the version once, expected "
            f"{current['version'] + 1}, got {final['version']}"
        )
