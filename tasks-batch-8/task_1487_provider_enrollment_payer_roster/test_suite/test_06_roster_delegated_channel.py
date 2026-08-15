"""Delegated credentialing channel: roster submission, line adjudication,
rollup arithmetic, supersession, and agreement gating (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_enrollment_record,
    assert_roster_file,
    assert_roster_line,
    assert_roster_rollup_invariant,
    confirm_line,
    create_active_agreement,
    create_claim,
    create_payer_config,
    create_practice_group,
    create_provider,
    find_record,
    get_agreement,
    get_claim,
    get_provider_balance,
    get_roster_line,
    get_roster_lines,
    roster_add_line,
    roster_term_line,
    set_clock,
    setup_group_provider_payer,
    submit_roster_file,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _setup_agreement():
    """Group + provider + payer + ACTIVE agreement. Returns all four dicts."""
    group = create_practice_group()
    provider = create_provider(group["id"])
    payer = create_payer_config()
    agreement = create_active_agreement(group["id"], payer["id"])
    return group, provider, payer, agreement


class TestRosterAddConfirmReleaseCascade:
    def test_add_confirm_creates_record_and_releases_held_claim(self, api):
        """PRD §3.5: "The created record starts `ACTIVE`, points back to the
        line via `source_roster_line_id`, takes the confirmed date as its
        `effective_date`, copies the line's `enrollment_scope` and
        `benefit_assignment`, stamps `last_revalidation_completed_at` from the
        logical clock, computes its revalidation schedule per §3.7, and then
        runs the claim-release cascade of §3.6."
        PRD §3.6: "When an enrollment record becomes `ACTIVE` with effective
        date E — through application approval or roster ADD confirmation —
        every `HELD` claim of that provider–payer pair whose `service_date` is
        on or after E transitions `HELD → RELEASED`, processed in service-date
        order with ties broken by creation order; `HELD` claims dated before E
        stay `HELD`."

        Design: Difficulty/transitive_cascade/roster_add_confirm_release_cascade
        """
        _, provider, payer, agreement = _setup_agreement()
        set_clock("2026-08-10T00:00:00Z")
        claim = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=12000,
        )
        assert claim["status"] == "HELD", "no covering record, holds enabled"

        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
        )
        line = get_roster_line(roster["id"], 0)
        confirmed = validate_success(
            api.confirm_roster_line(
                roster["id"], line["id"],
                {"confirmed_effective_date": "2026-08-01"}, PAYER_REP,
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"

        record = find_record(provider_id=provider["id"], payer_id=payer["id"])
        assert_enrollment_record(record)
        assert record["status"] == "ACTIVE"
        assert record["effective_date"] == "2026-08-01"
        assert record["source_roster_line_id"] == line["id"]
        assert record["benefit_assignment"] == "GROUP"
        assert record["enrollment_scope"] == "GROUP_LINK"

        # Hop 2: the parked claim (2026-08-05 >= 2026-08-01) is released.
        assert get_claim(claim["id"])["status"] == "RELEASED"

    def test_term_confirm_terminates_record_with_retro_cascade(self, api):
        """PRD §3.5: "For a `TERM` line, an enrollment record for the pair in
        `ACTIVE` or `PENDING_REVALIDATION` must exist, else
        `ERR_NO_ACTIVE_ENROLLMENT`; confirmation terminates that record with
        `termination_date` equal to the confirmed date, firing the full
        record-termination cascade of §3.8."

        Design: Difficulty/transitive_cascade/roster_add_confirm_release_cascade
        """
        _, provider, payer, agreement = _setup_agreement()
        roster1 = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
        )
        line1 = get_roster_line(roster1["id"], 0)
        confirm_line(roster1["id"], line1["id"], "2026-08-01")
        record = find_record(provider_id=provider["id"], payer_id=payer["id"])

        set_clock("2026-08-10T00:00:00Z")
        claim = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=4000,
        )
        assert claim["status"] == "RELEASED"

        agreement_now = get_agreement(agreement["id"])
        roster2 = submit_roster_file(
            agreement["id"], agreement_now["version"],
            [roster_term_line(provider["id"], expected_effective_date="2026-08-03")],
        )
        line2 = get_roster_line(roster2["id"], 0)
        confirmed = validate_success(
            api.confirm_roster_line(
                roster2["id"], line2["id"],
                {"confirmed_effective_date": "2026-08-03"}, PAYER_REP,
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"

        record_after = validate_success(
            api.get_enrollment_record(record["id"], OFFICER), 200
        )
        assert record_after["status"] == "TERMINATED"
        assert record_after["termination_date"] == "2026-08-03"
        # Retro cascade: the RELEASED claim (2026-08-05 >= 2026-08-03) is
        # recouped with its per-claim fee of round_half_up(4000 * 2%) = 80.
        claim_after = get_claim(claim["id"])
        assert claim_after["status"] == "RECOUPED"
        assert claim_after["recoupment_fee_cents"] == 80
        assert record_after["net_recouped_cents"] == 4080
        assert get_provider_balance(provider["id"]) == 4080


class TestRosterLineBucketConservation:
    def test_rollup_buckets_conserved_across_confirm_reject_resolve(self, api):
        """PRD §3.5: "`total_lines` counts all lines; `pending_count`,
        `confirmed_count`, `rejected_count`, `discrepancy_count`, and
        `superseded_count` count the lines in each corresponding state, and the
        five status counts always sum to `total_lines`."
        PRD §3.5: "While the file is `SUBMITTED`, its status is derived after
        every line mutation: any line still `PENDING` keeps the file
        `SUBMITTED`; with zero pending and every line `CONFIRMED` (and at least
        one line, which is guaranteed since empty rosters never exist), the
        file becomes `CONFIRMED`; otherwise — zero pending but some line
        rejected, superseded, or in discrepancy — it becomes
        `PARTIALLY_CONFIRMED`."

        Design: Difficulty/compensating_invariant/roster_line_bucket_conservation
        """
        group = create_practice_group()
        p1 = create_provider(group["id"], npi="NPI-P1", full_name="Dr One")
        p2 = create_provider(group["id"], npi="NPI-P2", full_name="Dr Two")
        p3 = create_provider(group["id"], npi="NPI-P3", full_name="Dr Three")
        payer = create_payer_config()
        agreement = create_active_agreement(group["id"], payer["id"])

        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [
                roster_add_line(p1["id"], expected_effective_date="2026-08-01"),
                roster_add_line(p2["id"], expected_effective_date="2026-08-01"),
                roster_add_line(p3["id"], expected_effective_date="2026-08-01"),
            ],
        )
        assert_roster_file(roster)
        assert roster["total_lines"] == 3 and roster["pending_count"] == 3
        assert roster["status"] == "SUBMITTED"
        l0, l1, l2 = get_roster_lines(roster["id"])

        # Step 1: clean confirm of line 0 (record created for p1).
        confirm_line(roster["id"], l0["id"], "2026-08-01")
        f1 = validate_success(api.get_roster_file(roster["id"], SPECIALIST), 200)
        assert_roster_rollup_invariant(f1)
        assert (f1["pending_count"], f1["confirmed_count"], f1["total_lines"]) == (2, 1, 3)
        assert f1["status"] == "SUBMITTED", "lines still PENDING keep the file SUBMITTED"

        # Step 2: reject line 1; mismatch-confirm line 2 -> DISCREPANCY.
        validate_success(
            api.reject_roster_line(
                roster["id"], l1["id"], {"reason": "not on panel"}, PAYER_REP,
            ),
            200,
        )
        l2_after = validate_success(
            api.confirm_roster_line(
                roster["id"], l2["id"],
                {"confirmed_effective_date": "2026-08-15"}, PAYER_REP,
            ),
            200,
        )
        assert l2_after["status"] == "DISCREPANCY"
        assert l2_after["confirmed_effective_date"] == "2026-08-15"
        f2 = validate_success(api.get_roster_file(roster["id"], SPECIALIST), 200)
        assert_roster_rollup_invariant(f2)
        assert (f2["pending_count"], f2["discrepancy_count"]) == (0, 1)
        assert f2["status"] == "PARTIALLY_CONFIRMED"

        # Step 3: resolve the discrepancy, accepting the confirmed date.
        resolved = validate_success(
            api.resolve_roster_line(
                roster["id"], l2["id"], {"accept_confirmed": True}, SPECIALIST,
            ),
            200,
        )
        assert resolved["status"] == "CONFIRMED"
        f3 = validate_success(api.get_roster_file(roster["id"], SPECIALIST), 200)
        assert_roster_rollup_invariant(f3)
        assert (f3["confirmed_count"], f3["rejected_count"], f3["pending_count"],
                f3["discrepancy_count"], f3["superseded_count"],
                f3["total_lines"]) == (2, 1, 0, 0, 0, 3)
        assert f3["status"] == "PARTIALLY_CONFIRMED"

        # The accepted discrepancy applied the deferred ADD effect at the
        # confirmed date (PRD §3.5).
        record_p3 = find_record(provider_id=p3["id"], payer_id=payer["id"])
        assert record_p3["effective_date"] == "2026-08-15"

    def test_discrepancy_decline_moves_line_to_rejected_with_fixed_reason(self, api):
        """PRD §3.5: "Declining moves the line to `REJECTED` with
        `rejection_reason` set to the fixed string `DISCREPANCY_DECLINED`."
        PRD §3.5: "When the confirmed date differs from the expected date, the
        line instead becomes `DISCREPANCY`, the `confirmed_effective_date` is
        recorded, and no enrollment effect of any kind is applied yet."

        Design: Difficulty/compensating_invariant/roster_line_bucket_conservation
        """
        group = create_practice_group()
        p1 = create_provider(group["id"], npi="NPI-P1", full_name="Dr One")
        p2 = create_provider(group["id"], npi="NPI-P2", full_name="Dr Two")
        payer = create_payer_config()
        agreement = create_active_agreement(group["id"], payer["id"])

        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [
                roster_add_line(p1["id"], expected_effective_date="2026-08-01"),
                roster_add_line(p2["id"], expected_effective_date="2026-08-01"),
            ],
        )
        l0, l1 = get_roster_lines(roster["id"])
        confirm_line(roster["id"], l0["id"], "2026-08-01")
        validate_success(
            api.confirm_roster_line(
                roster["id"], l1["id"],
                {"confirmed_effective_date": "2026-08-15"}, PAYER_REP,
            ),
            200,
        )

        declined = validate_success(
            api.resolve_roster_line(
                roster["id"], l1["id"], {"accept_confirmed": False}, SPECIALIST,
            ),
            200,
        )
        assert declined["status"] == "REJECTED"
        assert declined["rejection_reason"] == "DISCREPANCY_DECLINED"

        f = validate_success(api.get_roster_file(roster["id"], SPECIALIST), 200)
        assert_roster_rollup_invariant(f)
        assert (f["confirmed_count"], f["rejected_count"], f["total_lines"]) == (1, 1, 2)
        assert f["status"] == "PARTIALLY_CONFIRMED"

        # No enrollment record may exist for the declined line's provider.
        records = validate_success(
            api.list_enrollment_records(
                SPECIALIST, params={"provider_id": p2["id"], "payer_id": payer["id"]}
            ),
            200,
        )
        assert records == []


class TestRosterSubmissionGates:
    def test_submit_blocked_by_terminated_agreement_even_with_current_version(self, api):
        """PRD §3.4: "The agreement must be `ACTIVE`, else
        `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/roster_submit_blocked_by_terminated_agreement
        """
        _, provider, payer, agreement = _setup_agreement()
        terminated = validate_success(
            api.terminate_delegation_agreement(agreement["id"], OFFICER), 200
        )
        assert terminated["status"] == "TERMINATED"

        # Carry the agreement's CURRENT version so only the state gate can fire.
        res = api.create_roster_file(
            {
                "agreement_id": agreement["id"],
                "expected_agreement_version": terminated["version"],
                "lines": [roster_add_line(provider["id"])],
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_submit_blocked_by_expired_agreement(self, api):
        """PRD §3.4: "An agreement starts `ACTIVE`, becomes `EXPIRED` via the
        clock sweep once the current logical date passes `expiry_date`, and may
        be terminated early by a `ComplianceOfficer`, moving `ACTIVE →
        TERMINATED`; neither expiry nor termination cascades into roster files
        or enrollment records."
        PRD §3.4: "The agreement must be `ACTIVE`, else
        `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/roster_submit_blocked_by_terminated_agreement
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        payer = create_payer_config()
        agreement = create_active_agreement(
            group["id"], payer["id"],
            effective_date="2026-01-01", expiry_date="2026-10-31",
        )
        set_clock("2026-11-01T00:00:00Z")
        expired = get_agreement(agreement["id"])
        assert expired["status"] == "EXPIRED"

        res = api.create_roster_file(
            {
                "agreement_id": agreement["id"],
                "expected_agreement_version": expired["version"],
                "lines": [roster_add_line(provider["id"])],
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


class TestEmptyRosterBoundary:
    def test_empty_lines_rejected_and_nothing_persisted(self, api):
        """PRD §3.4: "With an agreement in force, an `EnrollmentSpecialist`
        submits a roster file carrying the `agreement_id`, the OCC field
        `expected_agreement_version` (§2.9), and a non-empty `lines` array — an
        empty array is rejected with `ERR_EMPTY_ROSTER`."

        Design: Difficulty/boundary_precision_check/empty_roster_rejected
        """
        _, _, _, agreement = _setup_agreement()
        res = api.create_roster_file(
            {
                "agreement_id": agreement["id"],
                "expected_agreement_version": agreement["version"],
                "lines": [],
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_EMPTY_ROSTER)

        files, meta = validate_paginated(
            api.list_roster_files(SPECIALIST, params={"agreement_id": agreement["id"]})
        )
        assert files == [] and meta["total_count"] == 0

    def test_single_line_roster_succeeds(self, api):
        """PRD §3.4: "A submitted file is born in `SUBMITTED` with every line
        `PENDING`, each line's `line_index` assigned zero-based in request
        order and its containing file recorded as `roster_file_id`."

        Design: Difficulty/boundary_precision_check/empty_roster_rejected
        """
        _, provider, _, agreement = _setup_agreement()
        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
        )
        assert_roster_file(roster)
        assert roster["status"] == "SUBMITTED"
        assert roster["total_lines"] == 1
        assert roster["pending_count"] == 1
        assert_roster_rollup_invariant(roster)

        lines = get_roster_lines(roster["id"])
        assert len(lines) == 1
        assert_roster_line(lines[0])
        assert lines[0]["status"] == "PENDING"
        assert lines[0]["line_index"] == 0
        assert lines[0]["roster_file_id"] == roster["id"]


class TestRosterLineConfirmGuards:
    def test_reconfirm_of_confirmed_line_rejected(self, api):
        """PRD §3.5: "Both actions require the line to be `PENDING` —
        confirming or rejecting any other line state fails with
        `ERR_ROSTER_LINE_NOT_PENDING` — and require the containing file to be
        `SUBMITTED`, else `ERR_INVALID_STATE_TRANSITION`; when both are
        violated, the line-level error is the one reported (§2.8)."

        Design: Corner/state_machines/roster_line_reconfirm_rejected
        """
        _, provider, payer, agreement = _setup_agreement()
        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
        )
        line = get_roster_line(roster["id"], 0)
        confirm_line(roster["id"], line["id"], "2026-08-01")

        res = api.confirm_roster_line(
            roster["id"], line["id"],
            {"confirmed_effective_date": "2026-08-01"}, PAYER_REP,
        )
        # The file is now CONFIRMED too, so both guards are violated and the
        # line-level error is reported first.
        validate_error(res, ApiErrorId.ERR_ROSTER_LINE_NOT_PENDING)

        records = validate_success(
            api.list_enrollment_records(
                SPECIALIST,
                params={"provider_id": provider["id"], "payer_id": payer["id"]},
            ),
            200,
        )
        assert len(records) == 1, "no duplicate record created by a re-confirm"

    def test_term_line_confirm_without_active_enrollment(self, api):
        """PRD §3.5: "For a `TERM` line, an enrollment record for the pair in
        `ACTIVE` or `PENDING_REVALIDATION` must exist, else
        `ERR_NO_ACTIVE_ENROLLMENT`; confirmation terminates that record with
        `termination_date` equal to the confirmed date, firing the full
        record-termination cascade of §3.8."

        Design: Corner/validations/term_line_confirm_without_active_enrollment
        """
        _, provider, _, agreement = _setup_agreement()
        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_term_line(provider["id"], expected_effective_date="2026-08-01")],
        )
        line = get_roster_line(roster["id"], 0)

        res = api.confirm_roster_line(
            roster["id"], line["id"],
            {"confirmed_effective_date": "2026-08-01"}, PAYER_REP,
        )
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_ENROLLMENT)

        after = validate_success(
            api.get_roster_file(roster["id"], SPECIALIST), 200
        )
        line_after = get_roster_line(roster["id"], 0)
        assert line_after["status"] == "PENDING"
        assert after["pending_count"] == 1


class TestRosterFileLifecycle:
    def test_supersede_replaces_prior_submission(self, api):
        """PRD §3.4: "Submission increments the agreement's `version` by one,
        and it supersedes the prior `SUBMITTED` file for the same agreement:
        that file moves to `SUPERSEDED`, its still-`PENDING` lines move to
        `SUPERSEDED` with it, and its rollup counts are recomputed."

        Design: Corner/state_machines/roster_supersede_replaces_prior_submission
        """
        _, provider, _, agreement = _setup_agreement()
        v1 = agreement["version"]
        roster_a = submit_roster_file(
            agreement["id"], v1,
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
        )
        v2 = get_agreement(agreement["id"])["version"]
        assert v2 == v1 + 1, "each successful submission increments the version"

        roster_b = submit_roster_file(
            agreement["id"], v2,
            [roster_add_line(provider["id"], expected_effective_date="2026-09-01")],
        )
        assert roster_b["status"] == "SUBMITTED"
        assert roster_b["id"] != roster_a["id"]
        assert get_agreement(agreement["id"])["version"] == v1 + 2

        old = validate_success(api.get_roster_file(roster_a["id"], SPECIALIST), 200)
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_count"] == 1
        assert_roster_rollup_invariant(old)
        old_line = get_roster_line(roster_a["id"], 0)
        assert old_line["status"] == "SUPERSEDED"

    def test_all_lines_confirmed_transitions_file_to_confirmed(self, api):
        """PRD §3.5: "While the file is `SUBMITTED`, its status is derived
        after every line mutation: any line still `PENDING` keeps the file
        `SUBMITTED`; with zero pending and every line `CONFIRMED` (and at least
        one line, which is guaranteed since empty rosters never exist), the
        file becomes `CONFIRMED`; otherwise — zero pending but some line
        rejected, superseded, or in discrepancy — it becomes
        `PARTIALLY_CONFIRMED`."

        Design: Corner/state_machines/roster_file_all_confirmed_compound_status
        """
        _, provider, _, agreement = _setup_agreement()
        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
        )
        assert roster["status"] == "SUBMITTED"
        line = get_roster_line(roster["id"], 0)

        confirm_line(roster["id"], line["id"], "2026-08-01")
        f = validate_success(api.get_roster_file(roster["id"], SPECIALIST), 200)
        assert f["status"] == "CONFIRMED"
        assert f["confirmed_count"] == 1 == f["total_lines"]


class TestAgreementExpiry:
    def test_expiry_is_strictly_after_expiry_date(self, api):
        """PRD §3.4: "An agreement starts `ACTIVE`, becomes `EXPIRED` via the
        clock sweep once the current logical date passes `expiry_date`, and may
        be terminated early by a `ComplianceOfficer`, moving `ACTIVE →
        TERMINATED`; neither expiry nor termination cascades into roster files
        or enrollment records."

        Design: Corner/state_machines/agreement_expiry_on_clock_sweep
        """
        group = create_practice_group()
        payer = create_payer_config()
        agreement = create_active_agreement(
            group["id"], payer["id"],
            effective_date="2026-01-01", expiry_date="2026-12-31",
        )

        set_clock("2026-12-31T00:00:00Z")  # the expiry date itself is covered
        assert get_agreement(agreement["id"])["status"] == "ACTIVE"

        set_clock("2027-01-01T00:00:00Z")  # strictly past expiry
        assert get_agreement(agreement["id"])["status"] == "EXPIRED"
