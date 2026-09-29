"""Optimistic concurrency, the funding-posture threshold and a partial cascade.

Every version quoted below is read back from the server rather than assumed,
because PRD 2.7 makes both `expected_capital_program_version` and
`expected_mutual_aid_pact_version` non-optional and a cascade can move a parent
version by more than one step.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_certified_retrofit_project,
    allocate,
    allocation_payload,
    aid_context,
    api_client,
    assert_all_null,
    assert_fields,
    assert_pact_conservation,
    assert_program_conservation,
    certified_levee_context,
    commit_aid,
    commitment_payload,
    create_capital_program,
    create_pact,
    create_ridge,
    fulfill_commitment,
    grant_submission_payload,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    read_analysis,
    read_asset,
    read_assessment,
    read_capital_program,
    read_commitment,
    read_pact,
    read_plan_cycle,
    read_project,
    revise_hazard_profile,
    submit_grant,
    validate_error,
    validate_success,
    withdraw_project,
)

# PRD 3.5's worked cost stacks: the PROTECT levee totals 51273600 and the
# ACCOMMODATE retrofit totals 35316000, which sum to exactly 86589600.
LEVEE_COST_CENTS = 51273600
RETROFIT_COST_CENTS = 35316000
BOTH_PROJECTS_COST_CENTS = 86589600
AID_WINDOW_START = "2026-09-05T00:00:00Z"
AID_WINDOW_END = "2026-09-20T00:00:00Z"


def _two_certified_projects_and_a_program(authorized_cents=100000000):
    """A certified levee and a certified retrofit in one cycle, plus a program."""
    context = certified_levee_context()
    retrofit = add_certified_retrofit_project(context, name="Harbor Pump Retrofit")
    program = create_capital_program(authorized_cents=authorized_cents)
    context.update(
        {"levee": read_project(context["project"]["id"]),
         "retrofit": retrofit,
         "program": program}
    )
    return context


def _six_units_already_drawn():
    """Ridge pledges ten units and Harbor draws six of them across the pact window."""
    context = aid_context()
    commitment = commit_aid(
        context["pact"]["id"], context["harbor"]["id"], context["asset"]["id"], 6,
        "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z", context["pact"]["version"],
    )
    context["commitment"] = commitment
    return context


class TestTheProgramVersionGatesTheAllocation:
    """A version read before someone else's allocation buys nothing."""

    def test_a_stale_expected_version_is_refused_and_writes_no_ledger_field(self):
        """The second caller quoted version 1 after the first had moved it to 2.

        PRD 2.7: "The allocation request must therefore supply
        `expected_capital_program_version`, which is not optional. If it does not equal
        the target `CapitalProgram`'s current `version` — because some other writer
        advanced the program since the client read it — the request is rejected with
        `ERR_STALE_PROGRAM_VERSION` (HTTP 412) and no ledger field is touched."  PRD 3.7
        places the check second, "evaluated before any ledger field is read for writing",
        and PRD 3.5 fixes what an unfunded project still reads: "`allocated_cents` and
        `reported_period_count` are both 0, and `capital_program_id` ... null until the
        action that produces each of them runs."

        Design: Corner/cross_cutting_complexity_layers/allocation_with_a_stale_expected_program_version_returns_412
        """
        context = _two_certified_projects_and_a_program()
        program_id = context["program"]["id"]
        assert context["program"]["version"] == 1, (
            f"a fresh program starts at version 1, got {context['program']['version']!r}"
        )

        first = allocate(program_id, context["levee"]["id"], LEVEE_COST_CENTS, 1)
        stale = api_client.allocate(
            program_id,
            allocation_payload(context["retrofit"]["id"], RETROFIT_COST_CENTS, 1),
            ADMIN(),
        )

        assert_fields(
            first,
            {"program_status": "PROGRAMMED", "allocated_cents": LEVEE_COST_CENTS,
             "capital_program_id": program_id},
            "the project the first allocation funded",
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value, 412)
        assert_fields(
            read_project(context["retrofit"]["id"]),
            {"program_status": "UNPROGRAMMED", "allocated_cents": 0,
             "capital_program_id": None},
            "the project whose stale allocation was refused",
        )
        program = read_capital_program(program_id)
        assert_fields(
            program,
            {"version": 2, "committed_cents": LEVEE_COST_CENTS,
             "available_cents": 100000000 - LEVEE_COST_CENTS},
            "the program the refused request must not have touched",
        )
        assert_program_conservation(program)

    def test_the_identical_body_succeeds_once_the_fresh_version_is_quoted(self):
        """Re-reading the program and resending the same amounts lands the allocation.

        PRD 2.7: "On success the program's `version` increments by 1, which means
        replaying the identical request with the same expected version is rejected on the
        second call."  PRD 3.7 then re-derives the posture: "`CLOSED` when
        `available_cents` is exactly zero; otherwise `OVERSUBSCRIBED` when
        `available_cents` is greater than zero and the remaining headroom — ten thousand
        times `available_cents` divided by `authorized_cents`, floored to whole basis
        points — is strictly below 1000 basis points"; the surviving headroom here is
        1341 basis points, so the program reads `OPEN`.

        Design: Corner/cross_cutting_complexity_layers/allocation_with_a_stale_expected_program_version_returns_412
        """
        context = _two_certified_projects_and_a_program()
        program_id = context["program"]["id"]
        allocate(program_id, context["levee"]["id"], LEVEE_COST_CENTS, 1)
        refreshed_version = read_capital_program(program_id)["version"]
        assert refreshed_version == 2, (
            "one successful allocation moves the program version by exactly 1, got "
            f"{refreshed_version!r}"
        )

        response = api_client.allocate(
            program_id,
            allocation_payload(context["retrofit"]["id"], RETROFIT_COST_CENTS,
                               refreshed_version),
            ADMIN(),
        )

        funded = validate_success(response, 200)
        assert_fields(
            funded,
            {"program_status": "PROGRAMMED", "allocated_cents": RETROFIT_COST_CENTS},
            "the project the retried allocation funded",
        )
        program = read_capital_program(program_id)
        assert_fields(
            program,
            {"version": 3, "committed_cents": BOTH_PROJECTS_COST_CENTS,
             "available_cents": 13410400, "funding_posture": "OPEN"},
            "the program after both allocations",
        )
        assert_program_conservation(program)


class TestThePactVersionGateOutranksCapacity:
    """One request is both stale and oversized; the version gate answers first."""

    def test_the_stale_draw_is_refused_on_the_version_not_on_the_capacity(self):
        """Eight units against a six-unit pledge draw 412, not 409.

        PRD 3.9 orders the commitment guards and puts the version fourth:
        "`expected_mutual_aid_pact_version` must equal the pact's current `version`, or
        `ERR_STALE_PACT_VERSION` (HTTP 412) — checked before any capacity arithmetic
        runs."  The capacity guard it pre-empts is the ninth: "The peak **unit load**
        must be less than or equal to the pact's `pledged_units`; a peak that exceeds the
        pledge yields `ERR_AID_CAPACITY_EXCEEDED`."  Guards 5 to 8 all pass here — the
        asset is shared, Harbor is not Ridge, the window lies inside the pledge and only
        two windows overlap against a limit of 3 — so the refusal is provably the version.

        Design: Corner/cross_cutting_complexity_layers/pact_version_mismatch_is_evaluated_before_capacity_and_returns_412
        """
        context = _six_units_already_drawn()
        pact_id = context["pact"]["id"]
        after_setup = read_pact(pact_id)
        assert_fields(
            after_setup,
            {"version": 2, "reserved_units": 6, "free_units": 4, "status": "OPEN"},
            "the pact after the six-unit draw",
        )

        response = api_client.create_commitment(
            pact_id,
            commitment_payload(context["harbor"]["id"], context["asset"]["id"], 8,
                               AID_WINDOW_START, AID_WINDOW_END, 1),
            make_jurisdiction_delegate_headers(context["harbor"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_STALE_PACT_VERSION.value, 412)
        unchanged = read_pact(pact_id)
        assert_fields(
            unchanged,
            {"version": 2, "reserved_units": 6, "free_units": 4, "status": "OPEN"},
            "the pact the refused draw must not have touched",
        )
        assert_pact_conservation(unchanged)

    def test_only_a_fresh_version_reveals_the_capacity_refusal_underneath(self):
        """At version 2 the same eight units draw 409, and four units fit exactly.

        PRD 3.9: "The peak **unit load** must be less than or equal to the pact's
        `pledged_units`; a peak that exceeds the pledge yields
        `ERR_AID_CAPACITY_EXCEEDED`. A peak landing exactly on `pledged_units` is
        admitted."  The admitted draw then re-derives the ledger: "`reserved_units` is set
        to the **peak** concurrent unit load over the pact's `COMMITTED` and `FULFILLED`
        commitments ... and `free_units` becomes `pledged_units` minus `reserved_units`",
        after which the status rule gives "`EXHAUSTED` when `free_units` is exactly 0".

        Design: Corner/cross_cutting_complexity_layers/pact_version_mismatch_is_evaluated_before_capacity_and_returns_412
        """
        context = _six_units_already_drawn()
        pact_id = context["pact"]["id"]
        harbor_id = context["harbor"]["id"]
        asset_id = context["asset"]["id"]
        fresh_version = read_pact(pact_id)["version"]

        oversized = api_client.create_commitment(
            pact_id,
            commitment_payload(harbor_id, asset_id, 8, AID_WINDOW_START, AID_WINDOW_END,
                               fresh_version),
            make_jurisdiction_delegate_headers(harbor_id),
        )
        admitted = api_client.create_commitment(
            pact_id,
            commitment_payload(harbor_id, asset_id, 4, AID_WINDOW_START, AID_WINDOW_END,
                               fresh_version),
            make_jurisdiction_delegate_headers(harbor_id),
        )

        validate_error(oversized, ApiErrorId.ERR_AID_CAPACITY_EXCEEDED.value, 409)
        commitment = validate_success(admitted, 201)
        assert_fields(
            commitment,
            {"committed_units": 4, "status": "COMMITTED"},
            "the draw that lands the peak exactly on the pledge",
        )
        pact = read_pact(pact_id)
        assert_fields(
            pact,
            {"version": 3, "reserved_units": 10, "free_units": 0, "status": "EXHAUSTED"},
            "the pact once the pledge is fully drawn",
        )
        assert_pact_conservation(pact)


class TestParentVersionsAdvanceOnlyWhenTheParentIsWritten:
    """The program moves on allocation and withdrawal; the pact ignores fulfilment."""

    @staticmethod
    def _a_funded_program_and_a_drawn_pact():
        context = certified_levee_context()
        harbor_id = context["harbor"]["id"]
        program = create_capital_program(authorized_cents=100000000)
        ridge = create_ridge()
        pact = create_pact(ridge["id"])
        commitment = commit_aid(
            pact["id"], harbor_id, context["asset"]["id"], 6,
            "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z", pact["version"],
        )
        context.update({"program": program, "ridge": ridge, "pact": pact,
                        "commitment": commitment})
        return context

    def test_the_program_version_moves_on_the_allocation_and_again_on_the_withdrawal(self):
        """Version 1 to 2 on the way in, 2 to 3 on the way out, ledger back to zero.

        PRD 3.7 on allocation: "The program's `version` increments by 1, and the allocated
        project's `version` increments by 1."  PRD 3.7 on withdrawal hop 2: "*Because* the
        project has left the committed set, the program's `committed_cents` decreases by
        exactly the released amount and `available_cents` increases by exactly the same
        amount, so `committed_cents` plus `available_cents` still equals
        `authorized_cents`", and the cascade closes with "The program's `version`
        increments by 1, and so does the `version` of every project row the cascade
        touches."  Hop 1 also fixes what the project keeps: "its `allocated_cents` is reset
        to 0. `capital_program_id` is deliberately **retained** for audit."

        Design: Corner/cross_cutting_complexity_layers/parent_versions_advance_on_every_write_that_touches_them
        """
        context = self._a_funded_program_and_a_drawn_pact()
        program_id = context["program"]["id"]
        project_id = context["project"]["id"]
        assert context["program"]["version"] == 1, (
            f"a fresh program starts at version 1, got {context['program']['version']!r}"
        )

        allocate(program_id, project_id, LEVEE_COST_CENTS, 1)
        after_allocation = read_capital_program(program_id)
        withdrawn = withdraw_project(project_id, context["harbor"]["id"])
        after_withdrawal = read_capital_program(program_id)

        assert_fields(
            after_allocation,
            {"version": 2, "committed_cents": LEVEE_COST_CENTS},
            "the program after the allocation",
        )
        assert_fields(
            withdrawn,
            {"program_status": "WITHDRAWN", "allocated_cents": 0,
             "capital_program_id": program_id},
            "the withdrawn project",
        )
        assert_fields(
            after_withdrawal,
            {"version": 3, "committed_cents": 0, "available_cents": 100000000,
             "funding_posture": "OPEN"},
            "the program after the withdrawal",
        )
        assert_program_conservation(after_withdrawal)

    def test_fulfilment_moves_the_commitment_alone_and_leaves_the_pact_untouched(self):
        """The commitment reaches version 2 while the pact stays at version 2.

        PRD 3.9: "Crucially, fulfilment leaves `reserved_units` and `free_units`
        **unchanged**, because a fulfilled commitment stays inside the reserved set — the
        units were actually consumed, so releasing them back to the pledge would be
        double-counting. Only the commitment's `version` increments by 1."  That is the
        exception to the commit path, where PRD 3.9 says "The pact's `version` increments
        by 1", and to the release path, where "Both the pact's `version` and the
        commitment's `version` increment by 1."

        Design: Corner/cross_cutting_complexity_layers/parent_versions_advance_on_every_write_that_touches_them
        """
        context = self._a_funded_program_and_a_drawn_pact()
        pact_id = context["pact"]["id"]
        commitment_id = context["commitment"]["id"]
        assert context["commitment"]["version"] == 1, (
            "a fresh commitment starts at version 1, got "
            f"{context['commitment']['version']!r}"
        )
        before = read_pact(pact_id)
        assert_fields(
            before,
            {"version": 2, "reserved_units": 6, "free_units": 4},
            "the pact after the six-unit draw",
        )

        fulfill_commitment(commitment_id, context["harbor"]["id"])

        assert_fields(
            read_commitment(commitment_id),
            {"status": "FULFILLED", "version": 2},
            "the fulfilled commitment",
        )
        after = read_pact(pact_id)
        assert_fields(
            after,
            {"version": 2, "reserved_units": 6, "free_units": 4},
            "the pact fulfilment must not have written",
        )
        assert_pact_conservation(after)


class TestTheGrantHoldFollowsTheFundingPosture:
    """The hold is derived from the posture on every write, never latched."""

    @staticmethod
    def _a_program_authorized_for_exactly_both_projects():
        return _two_certified_projects_and_a_program(
            authorized_cents=BOTH_PROJECTS_COST_CENTS
        )

    def test_the_allocation_that_zeroes_the_headroom_raises_the_hold(self):
        """4078 basis points of headroom leave the hold down; zero raises it.

        PRD 3.7: "Whenever the recomputed posture is `CLOSED`, the system sets
        `grant_hold_flag` to true on **every** project of that program whose
        `program_status` is `PROGRAMMED` — not merely on the project just funded."  The
        posture rule reached is "`CLOSED` when `available_cents` is exactly zero", and the
        submission refused by the raised flag is the fourth grant guard: "the project's
        `grant_hold_flag` must be false, or `ERR_GRANT_ON_HOLD`".

        Design: Corner/cross_cutting_complexity_layers/grant_hold_flag_is_raised_when_the_program_posture_closes_and_cleared_when_it_reopens
        """
        context = self._a_program_authorized_for_exactly_both_projects()
        program_id = context["program"]["id"]
        harbor_id = context["harbor"]["id"]
        levee_id = context["levee"]["id"]
        retrofit_id = context["retrofit"]["id"]

        allocate(program_id, levee_id, LEVEE_COST_CENTS, 1)
        open_program = read_capital_program(program_id)
        assert_fields(
            open_program,
            {"committed_cents": LEVEE_COST_CENTS, "available_cents": RETROFIT_COST_CENTS,
             "funding_posture": "OPEN"},
            "the program with 4078 basis points of headroom left",
        )
        assert_fields(
            submit_grant(levee_id, harbor_id, grant_funder="BRIC"),
            {"program_status": "GRANT_SUBMITTED", "grant_funder": "BRIC"},
            "the levee that applied while the posture was still OPEN",
        )

        # PRD 2.7: the request must quote the version the client last observed on
        # the parent record, and `open_program` was already re-read after the first
        # allocation moved the program from 1 to 2.
        allocate(program_id, retrofit_id, RETROFIT_COST_CENTS, open_program["version"])

        closed_program = read_capital_program(program_id)
        assert_fields(
            closed_program,
            {"committed_cents": BOTH_PROJECTS_COST_CENTS, "available_cents": 0,
             "funding_posture": "CLOSED"},
            "the program whose last cent is committed",
        )
        assert_program_conservation(closed_program)
        assert_fields(
            read_project(retrofit_id),
            {"program_status": "PROGRAMMED", "grant_hold_flag": True},
            "the programmed project the closure put on hold",
        )
        assert_fields(
            read_project(levee_id),
            {"program_status": "GRANT_SUBMITTED", "grant_hold_flag": False},
            "the already-submitted project, which is not in the PROGRAMMED set",
        )
        refused = api_client.submit_grant(
            retrofit_id, grant_submission_payload(grant_funder="BRIC"),
            make_project_sponsor_headers(harbor_id),
        )
        validate_error(refused, ApiErrorId.ERR_GRANT_ON_HOLD.value, 409)
        assert_fields(
            read_project(retrofit_id),
            {"program_status": "PROGRAMMED", "grant_funder": None},
            "the project whose application was held",
        )

    def test_a_withdrawal_reopens_the_program_and_clears_the_hold(self):
        """Hop 4 of the withdrawal cascade lets the held application through.

        PRD 3.7's withdrawal cascade: "**Hop 3.** *Because* `available_cents` has risen
        above zero, `funding_posture` is re-derived by the same ordered rule as above and
        therefore leaves `CLOSED`."  Hop 4: "*Because* the posture has left `CLOSED`,
        `grant_hold_flag` is cleared to false on **every sibling project** of that program
        whose `program_status` is `PROGRAMMED`."  Hop 1 also keeps the withdrawn project's
        paperwork: "On the `GRANT_SUBMITTED → WITHDRAWN` branch, `grant_funder` and
        `grant_submitted_at` are likewise retained."

        Design: Corner/cross_cutting_complexity_layers/grant_hold_flag_is_raised_when_the_program_posture_closes_and_cleared_when_it_reopens
        """
        context = self._a_program_authorized_for_exactly_both_projects()
        program_id = context["program"]["id"]
        harbor_id = context["harbor"]["id"]
        levee_id = context["levee"]["id"]
        retrofit_id = context["retrofit"]["id"]
        allocate(program_id, levee_id, LEVEE_COST_CENTS, 1)
        submit_grant(levee_id, harbor_id, grant_funder="BRIC")
        allocate(program_id, retrofit_id, RETROFIT_COST_CENTS,
                 read_capital_program(program_id)["version"])
        assert read_project(retrofit_id)["grant_hold_flag"] is True, (
            "the closure must have raised the hold before the withdrawal is tested"
        )

        withdrawn = withdraw_project(levee_id, harbor_id)

        assert_fields(
            withdrawn,
            {"program_status": "WITHDRAWN", "allocated_cents": 0,
             "grant_funder": "BRIC", "capital_program_id": program_id},
            "the withdrawn project, which keeps its paperwork",
        )
        reopened = read_capital_program(program_id)
        assert_fields(
            reopened,
            {"committed_cents": RETROFIT_COST_CENTS, "available_cents": LEVEE_COST_CENTS,
             "funding_posture": "OPEN"},
            "the program the withdrawal reopened",
        )
        assert_program_conservation(reopened)
        assert_fields(
            read_project(retrofit_id),
            {"grant_hold_flag": False},
            "the sibling whose hold hop 4 cleared",
        )
        assert_fields(
            submit_grant(retrofit_id, harbor_id, grant_funder="BRIC"),
            {"program_status": "GRANT_SUBMITTED", "grant_funder": "BRIC"},
            "the application the cleared hold let through",
        )


class TestTheRevisionCascadeIsConditionalPerHop:
    """Four hops land and the fifth is a no-op because no cycle is in a round."""

    def test_hops_one_to_four_land_while_the_draft_cycle_is_untouched(self):
        """The projection, assessment, asset, analysis and project all move; the cycle does not.

        PRD 3.2 hop 1: "The three projection fields are overwritten from the request,
        `published_version` increments by 1, and `published_at` is refreshed to the current
        logical clock instant."  Hop 2 moves the assessment "`ASSESSED → STALE`"; hop 3
        moves the asset "`RANKED → RECOMPUTE_REQUIRED`, and its `consequence_score`,
        `criticality_tier` and `dependency_depth` are all set to null"; hop 4 says "every
        benefit-cost analysis in `CERTIFIED` status whose project is linked to one of those
        assets moves `CERTIFIED → STALE` with `stale_reason` set to `ASSET_RECOMPUTE`, and
        the owning adaptation project's `analysis_status` moves `BCA_CERTIFIED →
        BCA_STALE`."  Hop 5 is guarded: "every plan cycle that owns one of them and
        currently sits in `ENDORSEMENT_ROUND` is pushed back", so a `DRAFT` cycle is
        outside its input set.

        Design: Corner/cross_cutting_complexity_layers/hazard_revision_cascade_stops_at_hop_four_when_no_cycle_is_in_an_endorsement_round
        """
        context = certified_levee_context()
        cycle_before = read_plan_cycle(context["cycle"]["id"])
        assert cycle_before["status"] == "DRAFT", (
            f"the cycle must still be DRAFT for hop 5 to be a no-op, got {cycle_before['status']!r}"
        )

        revised = revise_hazard_profile(context["profile"]["id"])

        assert_fields(
            revised,
            {"published_version": 2, "exposure_index": 0.90,
             "annual_event_probability": 0.03,
             "projected_annual_loss_cents": 300000000, "status": "PUBLISHED"},
            "the republished projection (hop 1)",
        )
        assert_fields(
            read_assessment(context["assessment"]["id"]),
            {"status": "STALE"},
            "the assessment the republication invalidated (hop 2)",
        )
        asset = read_asset(context["asset"]["id"])
        assert_fields(
            asset,
            {"criticality_status": "RECOMPUTE_REQUIRED"},
            "the asset the stale assessment unranked (hop 3)",
        )
        assert_all_null(
            asset,
            ("consequence_score", "criticality_tier", "dependency_depth"),
            "the unranked asset's discarded ranking outputs (hop 3)",
        )
        assert_fields(
            read_analysis(context["analysis"]["id"]),
            {"status": "STALE", "stale_reason": "ASSET_RECOMPUTE"},
            "the certified case the unranked asset invalidated (hop 4)",
        )
        assert_fields(
            read_project(context["project"]["id"]),
            {"analysis_status": "BCA_STALE"},
            "the owning project (hop 4)",
        )
        assert_fields(
            read_plan_cycle(context["cycle"]["id"]),
            {"status": "DRAFT", "revision_count": 0,
             "version": cycle_before["version"]},
            "the DRAFT cycle hop 5 left alone",
        )
