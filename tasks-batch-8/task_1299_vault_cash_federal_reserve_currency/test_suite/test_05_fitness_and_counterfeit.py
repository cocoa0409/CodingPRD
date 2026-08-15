"""Fitness batches (escrow, sort, settle tolerance, conservation across recount)
and counterfeit cases (seizure cascade, SoD, terminal lockdown, settle)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_counterfeit_case_payload,
    create_fitness_batch_payload,
    create_open_fitness_batch,
    create_seized_counterfeit_case,
    create_sorted_fitness_batch,
    create_staffed_site,
    get_success_data,
    get_site,
    validate_error,
    validate_paginated,
)

CONSERVATION_CITE = (
    'PRD §3.5: "The batch\'s `shrink_cents` — the unaccounted remainder — is '
    "computed as the input minus the three declared buckets, and a conservation "
    "invariant holds after every sort and after settlement: the input always "
    'equals fit recovered plus unfit remaining plus counterfeit face plus shrink."'
)
SETTLE_CITE = (
    'PRD §3.5: "Settling moves `SORTED → SETTLED` under a strict tolerance: '
    "`shrink_cents` must not exceed 500 cents — exactly 500 settles, 501 is "
    'rejected with `ERR_SHRINK_TOLERANCE_EXCEEDED` (HTTP 422)."'
)
AUTO_CASE_CITE = (
    'PRD §3.5: "When the sort found counterfeit notes, settlement also '
    "auto-creates a `CounterfeitCase` in `DETECTED` status linked to the batch "
    "via `fitness_batch_id`, denominated in 100-cent notes with a `note_count` "
    'equal to the counterfeit face divided by 100."'
)
SEIZE_CITE = (
    'PRD §3.6: "Seizure — `DETECTED → SEIZED` — is performed by a '
    "`VaultCustodian`, requires the case to currently be `DETECTED`, and records "
    "the acting identity in `seized_by_staff_id` and the logical clock in "
    "`seized_at`; seizing from any other state is rejected with "
    '`ERR_CASE_INVALID_STATE` (HTTP 409)."'
)
SOD_CITE = (
    'PRD §3.6: "From `SEIZED` the compliance path forks, and both forks enforce '
    "segregation of duties: the reporting or releasing `ComplianceOfficer` must "
    "not be the same identity recorded as `seized_by_staff_id`, failing with "
    '`ERR_SOD_VIOLATION` (HTTP 403) if they match."'
)


class TestFitnessConservationAcrossResort:
    def test_boundary_shrink_settles_and_recount_conserves(self, api):
        f"""{CONSERVATION_CITE}
        {SETTLE_CITE}
        {AUTO_CASE_CITE}
        PRD §3.5: "If the count needs correction, the custodian may reopen a
        `SORTED` batch, returning it to `OPEN` with all buckets reset to zero;
        settling or reopening from any state other than `SORTED` fails with
        `ERR_BATCH_INVALID_STATE`, and sorting and reopening each increment the
        batch version."

        Design: Difficulty/compensating_invariant/fitness_batch_conservation_across_resort
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"opening_fit_cents": 1000000, "opening_unfit_cents": 2000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        # Batch 1: shrink exactly 500 (inclusive boundary) — settles.
        b1 = create_open_fitness_batch(site_id, custodian, input_unfit_cents=1000000)
        sorted_b1 = get_success_data(
            api.record_sort_results(
                b1["id"],
                {
                    "fit_recovered_cents": 600000,
                    "unfit_remaining_cents": 399000,
                    "counterfeit_face_cents": 500,
                },
                custodian,
            )
        )
        assert sorted_b1["shrink_cents"] == 500
        assert 600000 + 399000 + 500 + sorted_b1["shrink_cents"] == 1000000
        settled_b1 = get_success_data(api.settle_fitness_batch(b1["id"], custodian))
        assert settled_b1["status"] == "SETTLED"

        # The auto-created counterfeit case is discoverable by batch linkage.
        cases, _meta = validate_paginated(
            api.list_counterfeit_cases(
                TEST_USERS["admin_headers"], params={"fitness_batch_id": b1["id"]}
            )
        )
        assert len(cases) == 1, f"expected one auto-created case, got {len(cases)}"
        assert cases[0]["status"] == "DETECTED"
        assert cases[0]["face_value_cents"] == 500
        assert cases[0]["note_count"] == 5

        # Batch 2: conservation survives a reopen/re-sort cycle with a new split.
        b2 = create_open_fitness_batch(site_id, custodian, input_unfit_cents=500000)
        round1 = get_success_data(
            api.record_sort_results(
                b2["id"],
                {
                    "fit_recovered_cents": 200000,
                    "unfit_remaining_cents": 300000,
                    "counterfeit_face_cents": 0,
                },
                custodian,
            )
        )
        assert 200000 + 300000 + 0 + round1["shrink_cents"] == 500000
        reopened = get_success_data(api.reopen_fitness_batch(b2["id"], custodian))
        assert reopened["status"] == "OPEN"
        assert reopened["fit_recovered_cents"] == 0
        assert reopened["unfit_remaining_cents"] == 0
        assert reopened["counterfeit_face_cents"] == 0

        round2 = get_success_data(
            api.record_sort_results(
                b2["id"],
                {
                    "fit_recovered_cents": 250000,
                    "unfit_remaining_cents": 249500,
                    "counterfeit_face_cents": 0,
                },
                custodian,
            )
        )
        assert round2["shrink_cents"] == 500
        assert 250000 + 249500 + 0 + round2["shrink_cents"] == 500000
        settled_b2 = get_success_data(api.settle_fitness_batch(b2["id"], custodian))
        assert settled_b2["status"] == "SETTLED"

    def test_zero_shrink_sort_settles_cleanly(self, api):
        f"""{CONSERVATION_CITE}
        {SETTLE_CITE}

        Design: Difficulty/compensating_invariant/fitness_batch_conservation_across_resort
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"opening_fit_cents": 1000000, "opening_unfit_cents": 1000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        batch = create_sorted_fitness_batch(
            site_id,
            custodian,
            input_unfit_cents=500000,
            fit_recovered_cents=300000,
            unfit_remaining_cents=200000,
            counterfeit_face_cents=0,
        )
        assert batch["shrink_cents"] == 0
        assert 300000 + 200000 + 0 + 0 == 500000
        settled = get_success_data(api.settle_fitness_batch(batch["id"], custodian))
        assert settled["status"] == "SETTLED"


class TestShrinkTolerance:
    def test_shrink_501_rejected_at_settle(self, api):
        f"""{SETTLE_CITE}

        Design: Corner/calculations/shrink_tolerance_501_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"opening_fit_cents": 1000000, "opening_unfit_cents": 1000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        batch = create_open_fitness_batch(site_id, custodian, input_unfit_cents=1000000)
        sorted_batch = get_success_data(
            api.record_sort_results(
                batch["id"],
                {
                    "fit_recovered_cents": 600000,
                    "unfit_remaining_cents": 399499,
                    "counterfeit_face_cents": 0,
                },
                custodian,
            )
        )
        assert sorted_batch["shrink_cents"] == 501

        site_before = get_site(site_id)
        resp = api.settle_fitness_batch(batch["id"], custodian)
        validate_error(resp, ApiErrorId.ERR_SHRINK_TOLERANCE_EXCEEDED)
        after = get_success_data(api.get_fitness_batch(batch["id"], custodian))
        assert after["status"] == "SORTED", (
            f"rejected settle must leave the batch SORTED, got {after['status']}"
        )
        site_after = get_site(site_id)
        assert site_after["on_hand_fit_cents"] == site_before["on_hand_fit_cents"], (
            "a rejected settle must post no ledger movement"
        )
        assert site_after["on_hand_unfit_cents"] == site_before["on_hand_unfit_cents"]


class TestBatchInvalidTransitions:
    def test_settle_from_open_rejected(self, api):
        """PRD §3.5: "If the count needs correction, the custodian may reopen a
        `SORTED` batch, returning it to `OPEN` with all buckets reset to zero;
        settling or reopening from any state other than `SORTED` fails with
        `ERR_BATCH_INVALID_STATE`, and sorting and reopening each increment the
        batch version."

        Design: Corner/state_machines/batch_settle_from_open_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"opening_fit_cents": 1000000, "opening_unfit_cents": 1000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        batch = create_open_fitness_batch(
            ctx["site"]["id"], custodian, input_unfit_cents=500000
        )
        resp = api.settle_fitness_batch(batch["id"], custodian)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)
        after = get_success_data(api.get_fitness_batch(batch["id"], custodian))
        assert after["status"] == "OPEN"

    def test_double_settle_rejected_and_applied_once(self, api):
        """PRD §3.5: "`SETTLED` is terminal."
        PRD §3.5: "Settlement returns the buckets to the site: `on_hand_fit_cents`
        increases by the recovered fit value and `on_hand_unfit_cents` by the
        remaining unfit value, booked as `FITNESS_RECLASS` ledger entries into the
        `FIT` and `UNFIT` buckets respectively on the clock date; a positive
        shrink posts an additional `ADJUSTMENT` entry removing the shrink from the
        `FIT` bucket."

        Design: Corner/state_machines/batch_double_settle_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"opening_fit_cents": 1000000, "opening_unfit_cents": 1000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]
        batch = create_sorted_fitness_batch(
            site_id,
            custodian,
            input_unfit_cents=500000,
            fit_recovered_cents=300000,
            unfit_remaining_cents=200000,
            counterfeit_face_cents=0,
        )
        get_success_data(api.settle_fitness_batch(batch["id"], custodian))

        resp = api.settle_fitness_batch(batch["id"], custodian)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)
        site = get_site(site_id)
        assert site["on_hand_fit_cents"] == 1300000, (
            f"the first settle must apply exactly once (1,000,000 + 300,000), "
            f"got {site['on_hand_fit_cents']}"
        )


class TestFitnessInsufficientUnfit:
    def test_input_above_unfit_balance_rejected_without_escrow(self, api):
        """PRD §3.5: "A `VaultCustodian` opens a `FitnessBatch` by declaring an
        `input_unfit_cents` amount, which is escrowed immediately: the site's
        `on_hand_unfit_cents` decreases by that amount, the site re-derives, and
        the batch lands in `OPEN`. The declared input must not exceed the site's
        unfit cash on hand, failing with `ERR_INSUFFICIENT_UNFIT_BALANCE`
        (HTTP 422), and a `FROZEN` site may not open batches at all
        (`ERR_VAULT_FROZEN`)."

        Design: Corner/validations/fitness_input_exceeds_unfit_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"opening_fit_cents": 1000000, "opening_unfit_cents": 100000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        resp = api.create_fitness_batch(
            create_fitness_batch_payload(site_id=site_id, input_unfit_cents=200000),
            custodian,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNFIT_BALANCE)
        site = get_site(site_id)
        assert site["on_hand_unfit_cents"] == 100000, (
            f"a rejected create must escrow nothing, got {site['on_hand_unfit_cents']}"
        )


class TestCounterfeitSeizeCascade:
    def test_seize_posts_ledger_and_debits_site_fit(self, api):
        f"""{SEIZE_CITE}
        PRD §3.6: "The face value leaves circulation immediately: a
        `COUNTERFEIT_SEIZURE` ledger entry posts the negative face value against
        the `FIT` bucket on the clock date, the site's `on_hand_fit_cents` falls
        accordingly, and the site cascade re-derives posture and refreshes
        reconciliations."
        PRD §3.6: "The case's `face_value_cents` is the denomination times the
        note count, and the case starts in `DETECTED`."

        Design: Difficulty/transitive_cascade/counterfeit_seize_cascade_debits_site
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",), site_overrides={"opening_fit_cents": 5000000}
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        u1_id = ctx["staff"]["custodian"]["id"]
        site_id = ctx["site"]["id"]

        case = get_success_data(
            api.create_counterfeit_case(
                create_counterfeit_case_payload(
                    site_id=site_id, denomination_cents=2000, note_count=25
                ),
                custodian,
            )
        )
        assert case["face_value_cents"] == 50000

        seized = get_success_data(api.seize_counterfeit_case(case["id"], custodian))
        assert seized["status"] == "SEIZED"
        assert seized["seized_by_staff_id"] == u1_id

        site = get_site(site_id)
        assert site["on_hand_fit_cents"] == 4950000, (
            f"5,000,000 - 50,000 via the ledger link, got {site['on_hand_fit_cents']}"
        )

        entries, _meta = validate_paginated(
            api.list_cash_ledger_entries(
                TEST_USERS["admin_headers"], params={"site_id": site_id}
            )
        )
        seizure_entries = [
            e for e in entries if e["entry_type"] == "COUNTERFEIT_SEIZURE"
        ]
        assert len(seizure_entries) == 1, (
            f"expected exactly one COUNTERFEIT_SEIZURE entry, got {len(seizure_entries)}"
        )
        assert seizure_entries[0]["signed_amount_cents"] == -50000
        assert seizure_entries[0]["bucket"] == "FIT"

    def test_seize_leaves_unfit_balance_untouched(self, api):
        f"""{SEIZE_CITE}
        PRD §3.6: "The face value leaves circulation immediately: a
        `COUNTERFEIT_SEIZURE` ledger entry posts the negative face value against
        the `FIT` bucket on the clock date, the site's `on_hand_fit_cents` falls
        accordingly, and the site cascade re-derives posture and refreshes
        reconciliations."

        Design: Difficulty/transitive_cascade/counterfeit_seize_cascade_debits_site
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"opening_fit_cents": 5000000, "opening_unfit_cents": 700000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]
        case = get_success_data(
            api.create_counterfeit_case(
                create_counterfeit_case_payload(
                    site_id=site_id, denomination_cents=2000, note_count=25
                ),
                custodian,
            )
        )
        get_success_data(api.seize_counterfeit_case(case["id"], custodian))
        site = get_site(site_id)
        assert site["on_hand_fit_cents"] == 4950000
        assert site["on_hand_unfit_cents"] == 700000, (
            "the seizure posts against the FIT bucket only"
        )


class TestCounterfeitStatePriorityOverSoD:
    def test_report_on_reported_case_yields_state_error_even_for_seizer(self, api):
        """PRD §2.8: "When a request fails several rules at once, the server
        reports the first failure in a fixed evaluation order: authentication
        context first (missing or invalid headers, then role permission, then
        site-scope or carrier ownership), then existence of path identifiers
        validated left-to-right along the URL, then existence of body-referenced
        foreign keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency)."
        PRD §3.6: "Both reporting and release require the case to be `SEIZED`, and
        settling requires it to be `REPORTED`; any wrong-state attempt is rejected
        with `ERR_CASE_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_sod_on_counterfeit_report
        """
        ctx = create_staffed_site(
            staff_roles=("custodian", "compliance"),
            site_overrides={"opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        u1_id = ctx["staff"]["custodian"]["id"]
        compliance = ctx["staff"]["compliance"]["headers"]
        site_id = ctx["site"]["id"]

        case = create_seized_counterfeit_case(site_id, custodian)
        get_success_data(api.report_counterfeit_case(case["id"], compliance))

        # The seizer, now wearing the ComplianceOfficer role, reports again: both
        # the state gate (case is REPORTED, not SEIZED) and SoD (reporter ==
        # seizer) are violated; the state machine precedes SoD in §2.8's order.
        from test_helpers import make_compliance_officer_headers

        resp = api.report_counterfeit_case(
            case["id"], make_compliance_officer_headers(u1_id)
        )
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
        after = get_success_data(api.get_counterfeit_case(case["id"], custodian))
        assert after["status"] == "REPORTED"

    def test_report_on_detected_case_yields_state_error(self, api):
        """PRD §2.8: "When a request fails several rules at once, the server
        reports the first failure in a fixed evaluation order: authentication
        context first (missing or invalid headers, then role permission, then
        site-scope or carrier ownership), then existence of path identifiers
        validated left-to-right along the URL, then existence of body-referenced
        foreign keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency)."
        PRD §3.6: "Both reporting and release require the case to be `SEIZED`, and
        settling requires it to be `REPORTED`; any wrong-state attempt is rejected
        with `ERR_CASE_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_sod_on_counterfeit_report
        """
        ctx = create_staffed_site(
            staff_roles=("custodian", "compliance"),
            site_overrides={"opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        compliance = ctx["staff"]["compliance"]["headers"]
        case = get_success_data(
            api.create_counterfeit_case(
                create_counterfeit_case_payload(
                    site_id=ctx["site"]["id"], denomination_cents=2000, note_count=25
                ),
                custodian,
            )
        )
        assert case["status"] == "DETECTED"
        resp = api.report_counterfeit_case(case["id"], compliance)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


class TestCounterfeitSoD:
    def test_report_by_seizer_rejected_peer_succeeds(self, api):
        f"""{SOD_CITE}
        PRD §3.6: "Reporting moves `SEIZED → REPORTED`, recording
        `reported_by_staff_id` and `reported_at`, and re-derives site posture —
        the overdue-report pressure that builds on aging `SEIZED` cases lifts once
        no case remains past its deadline."

        Design: Corner/validations/sod_report_by_seizer_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("custodian", "compliance"),
            site_overrides={"opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        u1_id = ctx["staff"]["custodian"]["id"]
        compliance = ctx["staff"]["compliance"]["headers"]
        u2_id = ctx["staff"]["compliance"]["id"]

        case = create_seized_counterfeit_case(ctx["site"]["id"], custodian)

        from test_helpers import make_compliance_officer_headers

        resp = api.report_counterfeit_case(
            case["id"], make_compliance_officer_headers(u1_id)
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        reported = get_success_data(api.report_counterfeit_case(case["id"], compliance))
        assert reported["status"] == "REPORTED"
        assert reported["reported_by_staff_id"] == u2_id


class TestCounterfeitTerminalLockdown:
    def test_seize_after_release_rejected_cash_stays_returned(self, api):
        """PRD §3.6: "Release moves `SEIZED → RELEASED` when the notes are
        determined genuine and returns the face value to circulation via a
        `COUNTERFEIT_RELEASE` ledger entry in the `FIT` bucket, again cascading."
        PRD §3.6: "`SETTLED_WITH_FED` and `RELEASED` are terminal, and every
        transition increments the case version."
        PRD §3.6: "Seizure — `DETECTED → SEIZED` — is performed by a
        `VaultCustodian`, requires the case to currently be `DETECTED`, and
        records the acting identity in `seized_by_staff_id` and the logical clock
        in `seized_at`; seizing from any other state is rejected with
        `ERR_CASE_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/case_terminal_lockdown_seize_after_release_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("custodian", "compliance"),
            site_overrides={"opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        compliance = ctx["staff"]["compliance"]["headers"]
        site_id = ctx["site"]["id"]

        case = create_seized_counterfeit_case(site_id, custodian)
        released = get_success_data(api.release_counterfeit_case(case["id"], compliance))
        assert released["status"] == "RELEASED"
        assert get_site(site_id)["on_hand_fit_cents"] == 5000000, (
            "seize -50,000 then release +50,000 must net to zero"
        )

        resp = api.seize_counterfeit_case(case["id"], custodian)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
        site = get_site(site_id)
        assert site["on_hand_fit_cents"] == 5000000, (
            f"the failed re-seize must apply nothing, got {site['on_hand_fit_cents']}"
        )


class TestComplianceOfficerLifecycle:
    def test_report_then_settle_reaches_terminal_without_cash_movement(self, api):
        """PRD §3.6: "Finally, settling a reported case moves `REPORTED →
        SETTLED_WITH_FED` with no cash movement — the seized face was already
        booked as a permanent loss at seize time. `SETTLED_WITH_FED` and
        `RELEASED` are terminal, and every transition increments the case
        version."
        PRD §3.6: "Reporting moves `SEIZED → REPORTED`, recording
        `reported_by_staff_id` and `reported_at`, and re-derives site posture —
        the overdue-report pressure that builds on aging `SEIZED` cases lifts once
        no case remains past its deadline."

        Design: Corner/rbac/compliance_officer_full_case_lifecycle
        """
        ctx = create_staffed_site(
            staff_roles=("custodian", "compliance"),
            site_overrides={"opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        compliance = ctx["staff"]["compliance"]["headers"]
        site_id = ctx["site"]["id"]

        case = create_seized_counterfeit_case(site_id, custodian)
        assert get_site(site_id)["on_hand_fit_cents"] == 4950000

        get_success_data(api.report_counterfeit_case(case["id"], compliance))
        settled = get_success_data(api.settle_counterfeit_case(case["id"], compliance))
        assert settled["status"] == "SETTLED_WITH_FED"
        site = get_site(site_id)
        assert site["on_hand_fit_cents"] == 4950000, (
            f"settle moves no cash — the seizure loss is permanent, "
            f"got {site['on_hand_fit_cents']}"
        )
