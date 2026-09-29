"""Rule violations and the matching satisfactions, one refusal at a time."""

from test_helpers import (
    add_certified_retrofit_project,
    ADMIN,
    aid_context,
    allocate,
    allocation_payload,
    api_client,
    ApiErrorId,
    assert_all_null,
    assert_fields,
    assert_program_conservation,
    asset_link_payload,
    award_grant,
    cast_endorsement,
    certified_levee_context,
    certified_retrofit_context,
    certify_analysis,
    commit_aid,
    commitment_payload,
    create_analysis,
    create_assessed_assessment,
    create_asset,
    create_asset_link,
    create_capital_program,
    create_harbor,
    create_plan_cycle,
    create_project,
    create_ridge,
    create_screened_project,
    create_session,
    endorsement_payload,
    engagement_session_payload,
    grant_equity_waiver,
    grant_submission_payload,
    indicator_report_payload,
    jurisdiction_payload,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    NON_EXISTENT_UUID,
    open_endorsement_round,
    open_engagement,
    patch_jurisdiction,
    project_payload,
    rank_asset,
    ranked_asset_context,
    read_capital_program,
    read_endorsement,
    read_pact,
    read_plan_cycle,
    read_project,
    read_session,
    screened_levee_context,
    session_completion_payload,
    submit_grant,
    validate_error,
    validate_paginated,
    validate_success,
)


def _cycle_at_endorsement_round(sponsor_id):
    """A cycle carrying one screened project and standing in round 1."""
    cycle = create_plan_cycle(required_session_count=0)
    create_screened_project(cycle["id"], sponsor_id)
    open_engagement(cycle["id"])
    open_endorsement_round(cycle["id"])
    return cycle


class TestJurisdictionCodeUniqueness:
    """The register's uniqueness key is the code and nothing else."""

    def test_a_second_member_reusing_a_code_is_refused(self):
        """A different name, population and score cannot rescue a duplicate code.

        PRD 3.1: "The `jurisdiction_code` must be 3 to 32 characters long and may contain
        only uppercase letters, digits and hyphens, and it must be unique across the whole
        register — admitting a second member with a code another member already holds is
        rejected with `ERR_DUPLICATE_JURISDICTION_CODE`."

        Design: Corner/validations/duplicate_jurisdiction_code_rejected
        """
        first = create_harbor()

        response = api_client.create_jurisdiction(
            jurisdiction_payload(
                name="Harbor Township",
                jurisdiction_code="CITY-HARBOR",
                population=25000,
                svi_score=0.31,
                endorsement_weight=2,
            ),
            ADMIN(),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_JURISDICTION_CODE.value, 409)
        rows, meta = validate_paginated(api_client.list_jurisdictions(ADMIN()))
        assert meta["total_count"] == 1, (
            "the refused admission must leave the register holding one member, but it "
            f"reported {meta['total_count']}"
        )
        assert rows[0]["id"] == first["id"], (
            "the surviving member must be the one admitted first, but the register "
            f"returned {rows[0]['id']!r}"
        )

    def test_changing_only_the_code_admits_an_otherwise_identical_member(self):
        """Name, population and score may all collide when the code differs.

        PRD 3.1: "The `jurisdiction_code` must be 3 to 32 characters long and may contain
        only uppercase letters, digits and hyphens, and it must be unique across the whole
        register — admitting a second member with a code another member already holds is
        rejected with `ERR_DUPLICATE_JURISDICTION_CODE`."  Nothing else in PRD 3.1 is
        declared unique: "The `name` must be a non-blank string of 1 to 120 characters."

        Design: Corner/validations/distinct_jurisdiction_code_satisfies_the_uniqueness_rule
        """
        first = create_harbor()

        response = api_client.create_jurisdiction(
            jurisdiction_payload(
                name="City of Harbor",
                jurisdiction_code="TOWN-RIDGE",
                population=180000,
                svi_score=0.62,
                endorsement_weight=4,
            ),
            ADMIN(),
        )

        second = validate_success(response, 201)
        assert_fields(
            second,
            {
                "name": "City of Harbor",
                "jurisdiction_code": "TOWN-RIDGE",
                "population": 180000,
                "svi_score": 0.62,
                "endorsement_weight": 4,
                "status": "ACTIVE",
            },
            "the member admitted under a free code",
        )
        assert second["id"] != first["id"], (
            "the two members must be separate rows, but both reported the identifier "
            f"{second['id']!r}"
        )
        _rows, meta = validate_paginated(api_client.list_jurisdictions(ADMIN()))
        assert meta["total_count"] == 2, (
            f"the register must hold both members, but it reported {meta['total_count']}"
        )


class TestAssetLinkUniqueness:
    """A project may attribute benefit to any one asset exactly once."""

    def test_relinking_the_same_asset_is_refused(self):
        """A different avoided loss and equity flag cannot rescue a duplicate pair.

        PRD 3.6: "That check runs before the uniqueness check: a project may not link the
        same asset twice, and posting a `project_id` and `asset_id` pair that already
        exists is rejected with `ERR_DUPLICATE_ASSET_LINK`."  The surviving link keeps the
        sequence PRD 3.6 gave it: "Each accepted link is stamped with a `link_sequence`
        equal to one plus the count of links already held by that project, ordered by
        `created_at` ascending".

        Design: Corner/validations/duplicate_project_asset_link_rejected
        """
        context = screened_levee_context()
        harbor_id = context["harbor"]["id"]
        project_id = context["project"]["id"]
        first = validate_success(
            api_client.create_asset_link(
                project_id,
                asset_link_payload(context["asset"]["id"], 3333333, benefit_reaches_disadvantaged=True),
                make_project_sponsor_headers(harbor_id),
            ),
            201,
        )

        response = api_client.create_asset_link(
            project_id,
            asset_link_payload(context["asset"]["id"], 9999999, benefit_reaches_disadvantaged=False),
            make_project_sponsor_headers(harbor_id),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_ASSET_LINK.value, 409)
        rows, meta = validate_paginated(
            api_client.list_asset_links(ADMIN(), params={"project_id": project_id})
        )
        assert meta["total_count"] == 1, (
            f"the project must still hold exactly one link, but it reported {meta['total_count']}"
        )
        assert_fields(
            rows[0],
            {
                "id": first["id"],
                "avoided_loss_annual_cents": 3333333,
                "benefit_reaches_disadvantaged": True,
                "link_sequence": 1,
            },
            "the surviving first link",
        )


class TestEndorsementPayloadRules:
    """One live vote per member per round, and a note only where a note is meant."""

    def test_a_second_cast_in_the_same_round_is_refused(self):
        """The live row for the round blocks a re-cast even with a different decision.

        PRD 3.8: "no endorsement may already exist for the same combination of
        `plan_cycle_id`, `jurisdiction_id` and `round_number` carrying a live decision, or
        `ERR_DUPLICATE_ENDORSEMENT` — note that an endorsement already marked `SUPERSEDED`
        does not block a fresh cast, which is exactly what lets a member re-vote in the
        next round".

        Design: Corner/validations/duplicate_endorsement_in_the_same_round_rejected
        """
        harbor = create_harbor()
        create_ridge()
        cycle = _cycle_at_endorsement_round(harbor["id"])
        first = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")

        response = api_client.cast_endorsement(
            cycle["id"],
            endorsement_payload(harbor["id"], decision="VETOED"),
            make_jurisdiction_delegate_headers(harbor["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_ENDORSEMENT.value, 409)
        assert_fields(
            read_endorsement(first["id"]),
            {"decision": "ENDORSED", "round_number": 1, "weight_at_cast": 4, "version": 1},
            "the vote already on the record",
        )
        _rows, meta = validate_paginated(
            api_client.list_endorsements(ADMIN(), params={"plan_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the round must hold one endorsement, but it reported {meta['total_count']}"
        )

    def test_a_conditioned_decision_without_a_note_is_refused(self):
        """The note is required for CONDITIONED and admitted for nothing else.

        PRD 3.8: "A `CONDITIONED` decision must be accompanied by a `condition_note` of 1
        to 500 characters, and the note must be absent on any other decision."  The refusal
        code and status come from the same guard list: "`condition_note` must be present
        and non-empty when the decision is `CONDITIONED`, or `ERR_CONDITION_NOTE_REQUIRED`
        (HTTP 422)".

        Design: Corner/validations/conditioned_endorsement_without_a_condition_note_rejected
        """
        harbor = create_harbor()
        create_ridge()
        cycle = _cycle_at_endorsement_round(harbor["id"])

        refused = api_client.cast_endorsement(
            cycle["id"],
            endorsement_payload(harbor["id"], decision="CONDITIONED"),
            make_jurisdiction_delegate_headers(harbor["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_CONDITION_NOTE_REQUIRED.value, 422)
        _rows, meta = validate_paginated(
            api_client.list_endorsements(ADMIN(), params={"plan_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 0, (
            f"a refused cast writes nothing, but the round reported {meta['total_count']} rows"
        )

        accepted = api_client.cast_endorsement(
            cycle["id"],
            endorsement_payload(
                harbor["id"],
                decision="CONDITIONED",
                condition_note="Fund the cooling centres before adoption.",
            ),
            make_jurisdiction_delegate_headers(harbor["id"]),
        )

        assert_fields(
            validate_success(accepted, 201),
            {
                "decision": "CONDITIONED",
                "condition_note": "Fund the cooling centres before adoption.",
                "round_number": 1,
                "weight_at_cast": 4,
            },
            "the identical cast carrying its note",
        )


class TestEngagementSessionPayloadRules:
    """Attendance cannot exceed itself and a window cannot have zero length."""

    def test_more_disadvantaged_attendees_than_attendees_is_refused(self):
        """80 total against 90 disadvantaged leaves the session untouched.

        PRD 3.8: "then `disadvantaged_attendee_count` may not exceed `attendee_count`, or
        the request is rejected with `ERR_ATTENDANCE_MISMATCH` (HTTP 422)."  Nothing is
        written on the refusal, so the row keeps the state PRD 3.8 gives a fresh booking:
        "A newly scheduled session reads `status` `SCHEDULED` with `attendee_count`,
        `disadvantaged_attendee_count`, `equity_reach_bps` and `preferred_strategy_type`
        all null."

        Design: Corner/validations/session_completion_with_more_disadvantaged_than_total_attendees_rejected
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=1)
        session = create_session(cycle["id"], harbor["id"])

        response = api_client.complete_engagement_session(
            session["id"],
            session_completion_payload(attendee_count=80, disadvantaged_attendee_count=90),
            make_jurisdiction_delegate_headers(harbor["id"]),
        )

        validate_error(response, ApiErrorId.ERR_ATTENDANCE_MISMATCH.value, 422)
        stored = read_session(session["id"])
        assert_fields(stored, {"status": "SCHEDULED", "version": 1}, "the untouched session")
        assert_all_null(
            stored,
            (
                "attendee_count",
                "disadvantaged_attendee_count",
                "equity_reach_bps",
                "preferred_strategy_type",
            ),
            "the untouched session",
        )

    def test_a_window_whose_start_equals_its_end_is_refused(self):
        """A zero-length booking fails the strict inequality and writes nothing.

        PRD 2.5: "Wherever a payload carries a `window_start` and a `window_end` —
        scheduling an engagement session, creating a mutual aid pact, and creating a mutual
        aid commitment — `window_start` must be strictly earlier than `window_end`, or the
        request is rejected with `ERR_INVALID_WINDOW` (HTTP 422). All three of those
        operations are subject to this rule."

        Design: Corner/validations/session_window_with_equal_start_and_end_rejected
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=1)

        response = api_client.create_engagement_session(
            cycle["id"],
            engagement_session_payload(
                harbor["id"],
                window_start="2026-09-10T17:00:00Z",
                window_end="2026-09-10T17:00:00Z",
            ),
            make_jurisdiction_delegate_headers(harbor["id"]),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value, 422)
        _rows, meta = validate_paginated(
            api_client.list_engagement_sessions(ADMIN(), params={"plan_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the refused booking must write nothing, but the cycle reported {meta['total_count']}"
        )


class TestMutualAidWindowAndCounterparty:
    """A commitment must sit inside the pledge and must cross a member boundary."""

    def test_a_commitment_ending_one_second_late_is_refused(self):
        """The pact's own end instant is admissible; one second past it is not.

        PRD 3.9: "The commitment window must lie **inside** the pact window: its
        `window_start` must be at or after the pact's `window_start` and its `window_end` at
        or before the pact's `window_end`, or `ERR_AID_WINDOW_OUTSIDE_PACT` (HTTP 422)."
        The accepted call then behaves as PRD 3.9 describes: "A successful commitment reads
        `status` `COMMITTED` with `released_at` and `fulfilled_at` both null".

        Design: Corner/validations/aid_commitment_window_reaching_past_the_pact_rejected
        """
        context = aid_context()
        pact = context["pact"]
        harbor_id = context["harbor"]["id"]

        refused = api_client.create_commitment(
            pact["id"],
            commitment_payload(
                harbor_id,
                context["asset"]["id"],
                4,
                "2026-09-05T00:00:00Z",
                "2026-10-01T00:00:01Z",
                expected_mutual_aid_pact_version=1,
            ),
            make_jurisdiction_delegate_headers(harbor_id),
        )
        validate_error(refused, ApiErrorId.ERR_AID_WINDOW_OUTSIDE_PACT.value, 422)
        assert_fields(
            read_pact(pact["id"]),
            {"reserved_units": 0, "free_units": 10, "status": "OPEN", "version": 1},
            "the pledge the refused request never touched",
        )

        accepted = api_client.create_commitment(
            pact["id"],
            commitment_payload(
                harbor_id,
                context["asset"]["id"],
                4,
                "2026-09-05T00:00:00Z",
                "2026-10-01T00:00:00Z",
                expected_mutual_aid_pact_version=1,
            ),
            make_jurisdiction_delegate_headers(harbor_id),
        )

        committed = validate_success(accepted, 201)
        assert_fields(
            committed,
            {"status": "COMMITTED", "committed_units": 4, "released_at": None, "fulfilled_at": None},
            "the commitment ending exactly at the pledge's end",
        )
        assert_fields(
            read_pact(pact["id"]),
            {"reserved_units": 4, "free_units": 6, "status": "OPEN", "version": 2},
            "the pledge after the admitted draw",
        )

    def test_the_host_cannot_draw_on_its_own_pledge(self):
        """Ridge requesting from Ridge's pact is refused; Harbor's request is not.

        PRD 3.9: "`requesting_jurisdiction_id` must differ from the pact's
        `host_jurisdiction_id`; a member may not request aid from its own pledge, and the
        attempt yields `ERR_SELF_AID_NOT_ALLOWED`."  The shared-asset gate cannot be the
        reason, because PRD 3.9 checks it first — "The named lifeline asset's `is_shared`
        must be true, because only shared assets may be supported across jurisdictional
        lines; otherwise `ERR_ASSET_NOT_SHARED`" — and this asset is shared.

        Design: Corner/validations/aid_commitment_requested_by_the_host_itself_rejected
        """
        context = aid_context()
        pact = context["pact"]
        ridge_id = context["ridge"]["id"]
        harbor_id = context["harbor"]["id"]

        refused = api_client.create_commitment(
            pact["id"],
            commitment_payload(
                ridge_id,
                context["asset"]["id"],
                2,
                "2026-09-05T00:00:00Z",
                "2026-09-15T00:00:00Z",
                expected_mutual_aid_pact_version=1,
            ),
            make_jurisdiction_delegate_headers(ridge_id),
        )
        validate_error(refused, ApiErrorId.ERR_SELF_AID_NOT_ALLOWED.value, 409)
        assert_fields(
            read_pact(pact["id"]),
            {"reserved_units": 0, "free_units": 10, "version": 1},
            "the pledge the host could not draw on",
        )

        crossing = commit_aid(
            pact["id"],
            harbor_id,
            context["asset"]["id"],
            2,
            "2026-09-05T00:00:00Z",
            "2026-09-15T00:00:00Z",
        )

        assert_fields(
            crossing,
            {"status": "COMMITTED", "requesting_jurisdiction_id": harbor_id, "committed_units": 2},
            "the commitment that crosses a member boundary",
        )


class TestPrerequisiteEdges:
    """The dependency edge is acyclic, and it gates the grant on an award.

    PRD 3.5 states the walk: "the chain of `prerequisite_project_id` pointers walked
    upward from the new project must reach a null without revisiting any identifier;
    pointing a prerequisite at a project that already depends on the new one is
    rejected with `ERR_PROJECT_PREREQUISITE_CYCLE`."
    """

    def test_repointing_a_prerequisite_into_a_cycle_is_refused(self):
        """An unknown identifier is reported before the chain is ever walked.

        PRD 3.5: "Rewriting the prerequisite edge re-walks the chain for a repeated
        identifier and can therefore raise `ERR_PROJECT_PREREQUISITE_CYCLE` just as creation
        can."  The unknown identifier is caught earlier, by PRD 2.5's fifth rung: "a body
        `project_id` or `prerequisite_project_id` yields `ERR_PROJECT_NOT_FOUND`", which
        sits above every domain rule because "Everything from priority 9 downwards is
        domain logic".

        Design: Corner/validations/project_prerequisite_repointed_into_a_cycle_rejected
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=0)
        upstream = create_project(cycle["id"], harbor["id"], name="Upstream Levee")
        downstream = create_project(
            cycle["id"],
            harbor["id"],
            name="Downstream Pump",
            prerequisite_project_id=upstream["id"],
        )
        sponsor = make_project_sponsor_headers(harbor["id"])

        unknown = api_client.patch_project(
            upstream["id"], {"prerequisite_project_id": NON_EXISTENT_UUID}, sponsor
        )
        validate_error(unknown, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)

        loop = api_client.patch_project(
            upstream["id"], {"prerequisite_project_id": downstream["id"]}, sponsor
        )

        validate_error(loop, ApiErrorId.ERR_PROJECT_PREREQUISITE_CYCLE.value, 409)
        assert_fields(
            read_project(upstream["id"]),
            {"prerequisite_project_id": None, "version": 1},
            "the project whose edge neither attempt rewrote",
        )
        assert_fields(
            read_project(downstream["id"]),
            {"prerequisite_project_id": upstream["id"], "version": 1},
            "the surviving one-way dependency",
        )

    def test_a_grant_waits_for_the_prerequisite_to_be_awarded(self):
        """Programming the prerequisite is not enough; only its award opens the gate.

        PRD 3.7: "the project's `prerequisite_project_id` must be null or the prerequisite
        project's own `program_status` must already be `AWARDED`, or
        `ERR_PREREQUISITE_NOT_AWARDED`".  PRD 3.7 then admits the identical retry once the
        award lands: "On success the project moves `PROGRAMMED → GRANT_SUBMITTED`,
        `grant_funder` and `grant_submitted_at` are written from the request and the logical
        clock respectively, and the project's `version` increments by 1."

        Design: Corner/validations/grant_submission_before_the_prerequisite_award_rejected
        """
        context = certified_retrofit_context(project_overrides={"name": "Prerequisite Retrofit"})
        harbor_id = context["harbor"]["id"]
        prerequisite = context["project"]
        dependent = add_certified_retrofit_project(
            context, name="Dependent Retrofit", prerequisite_project_id=prerequisite["id"]
        )
        program = create_capital_program(authorized_cents=100000000)
        allocate(program["id"], prerequisite["id"], 30000000)
        allocate(program["id"], dependent["id"], 30000000)
        sponsor = make_project_sponsor_headers(harbor_id)

        too_early = api_client.submit_grant(dependent["id"], grant_submission_payload(), sponsor)
        validate_error(too_early, ApiErrorId.ERR_PREREQUISITE_NOT_AWARDED.value, 409)
        assert_fields(
            read_project(dependent["id"]),
            {"program_status": "PROGRAMMED", "grant_funder": None, "grant_submitted_at": None},
            "the dependent project still waiting",
        )

        submit_grant(prerequisite["id"], harbor_id)
        awarded = award_grant(prerequisite["id"])
        retried = api_client.submit_grant(dependent["id"], grant_submission_payload(), sponsor)

        assert_fields(awarded, {"program_status": "AWARDED"}, "the prerequisite project")
        assert_fields(
            validate_success(retried, 200),
            {"program_status": "GRANT_SUBMITTED", "grant_funder": "BRIC"},
            "the dependent project admitted after the award",
        )


def _two_link_equity_context():
    """A project whose links give it an equity share of exactly 2000 basis points.

    The shared water plant carries 1000000 of avoided loss that reaches disadvantaged
    communities and the unshared ring road carries 4000000 that does not, so PRD 3.7's
    share is ten thousand times one fifth, floored.
    """
    context = ranked_asset_context()
    harbor_id = context["harbor"]["id"]
    ring_road = create_asset(
        harbor_id,
        name="Harbor Ring Road",
        asset_class="TRANSPORT",
        replacement_value_cents=400000000,
        service_population=50000,
        redundancy_factor=0.20,
        is_shared=False,
    )
    create_assessed_assessment(
        context["profile"]["id"],
        ring_road["id"],
        sensitivity_score=0.40,
        adaptive_capacity_score=0.60,
    )
    ranked_road = rank_asset(ring_road["id"])
    cycle = create_plan_cycle(required_session_count=0)
    project = create_screened_project(cycle["id"], harbor_id, name="Ring Road Hardening")
    create_asset_link(
        project["id"], harbor_id, context["asset"]["id"], 1000000,
        benefit_reaches_disadvantaged=True,
    )
    create_asset_link(
        project["id"], harbor_id, ring_road["id"], 4000000,
        benefit_reaches_disadvantaged=False,
    )
    analysis = certify_analysis(
        create_analysis(project["id"], harbor_id, method="ANNUALIZED_EQUIVALENT")["id"]
    )
    context.update(
        {
            "ring_road": ranked_road,
            "cycle": cycle,
            "project": project,
            "analysis": analysis,
            "program": create_capital_program(authorized_cents=100000000),
        }
    )
    return context


class TestProgramEquityGate:
    """The floor refuses the allocation, and only the waiver relaxes it."""

    def test_a_project_below_the_equity_target_cannot_be_programmed(self):
        """2000 basis points against a 4000 target refuses without touching the ledger.

        PRD 3.7: "The project's `equity_benefit_share_bps` must be at least the program's
        `equity_target_bps`, **or** the project's `equity_waiver_granted` must be true;
        otherwise `ERR_EQUITY_FLOOR_NOT_MET`."  The share itself is PRD 3.7's floored
        quotient: "`equity_benefit_share_bps` is ten thousand times the sum of
        `avoided_loss_annual_cents` over the links whose `benefit_reaches_disadvantaged` is
        true, divided by the sum of `avoided_loss_annual_cents` over **all** the project's
        links, **floored** to a whole number of basis points."

        Design: Corner/validations/allocation_below_the_program_equity_floor_rejected
        """
        context = _two_link_equity_context()
        program = context["program"]

        response = api_client.allocate(
            program["id"],
            allocation_payload(context["project"]["id"], 51273600, 1),
            ADMIN(),
        )

        validate_error(response, ApiErrorId.ERR_EQUITY_FLOOR_NOT_MET.value, 409)
        assert_fields(
            read_project(context["project"]["id"]),
            {
                "program_status": "UNPROGRAMMED",
                "allocated_cents": 0,
                "capital_program_id": None,
                "priority_score": None,
            },
            "the project the equity floor refused",
        )
        untouched = read_capital_program(program["id"])
        assert_fields(
            untouched,
            {
                "committed_cents": 0,
                "available_cents": 100000000,
                "equity_committed_cents": 0,
                "equity_achieved_bps": 0,
                "funding_posture": "OPEN",
                "version": 1,
            },
            "the program ledger the refusal left alone",
        )
        assert_program_conservation(untouched)

    def test_the_waiver_opens_the_gate_without_rewriting_the_score(self):
        """The same project programs at priority 0.5043 on an un-waived 2000 bps share.

        PRD 3.7: "The **equity waiver** is the escape valve on the third check, and it
        belongs exclusively to the `EquityOfficer`. The request carries a
        `waiver_rationale` recording why the exception is justified, sets
        `equity_waiver_granted` to true on the project, and increments the project's
        `version` by 1. A waived project clears the equity gate no matter how low its equity
        benefit share is."  The score still reads the real share, because PRD 3.7's equity
        component "is `equity_benefit_share_bps` divided by ten thousand, capped at
        1.0000", and the ledger still excludes it: "`equity_committed_cents` is the sum of
        `allocated_cents` restricted to those projects whose `equity_benefit_share_bps` is
        at least the program's `equity_target_bps`."

        Design: Corner/validations/equity_waiver_satisfies_the_floor_and_admits_the_allocation
        """
        context = _two_link_equity_context()
        program = context["program"]
        project_id = context["project"]["id"]

        waived = grant_equity_waiver(
            project_id,
            waiver_rationale="Ring Road is the sole evacuation route for the Harbor mobile-home park.",
        )
        assert_fields(
            waived,
            {"equity_waiver_granted": True, "program_status": "UNPROGRAMMED"},
            "the waived project before any capital moved",
        )

        funded = validate_success(
            api_client.allocate(
                program["id"], allocation_payload(project_id, 51273600, 1), ADMIN()
            ),
            200,
        )

        assert_fields(
            funded,
            {
                "program_status": "PROGRAMMED",
                "allocated_cents": 51273600,
                "capital_program_id": program["id"],
                "equity_benefit_share_bps": 2000,
                "priority_score": 0.5043,
            },
            "the waived project now programmed",
        )
        ledger = read_capital_program(program["id"])
        assert_fields(
            ledger,
            {
                "committed_cents": 51273600,
                "available_cents": 48726400,
                "equity_committed_cents": 0,
                "equity_achieved_bps": 0,
                "funding_posture": "OPEN",
            },
            "the ledger that counts the money but not the equity",
        )
        assert_program_conservation(ledger)


class TestJurisdictionStandingGate:
    """A suspended member sponsors nothing until it is reinstated."""

    def test_a_suspended_member_cannot_propose_and_an_active_one_can(self):
        """The identical payload is refused, then accepted after reinstatement.

        PRD 3.5: "Proposal is gated three ways. The sponsoring jurisdiction must be
        `ACTIVE`."  PRD 3.1 supplies the reinstatement: "Amending a member is likewise
        reserved to a `RegionalAdministrator`, who may supply any combination of `status`,
        `endorsement_weight` and `svi_score`."  On acceptance the row reads the defaults PRD
        3.5 declares: "A freshly proposed project reads `screening_status` `PROPOSED`,
        `analysis_status` `NOT_ANALYZED`, `program_status` `UNPROGRAMMED` and
        `implementation_status` `NOT_STARTED`."

        Design: Corner/validations/project_creation_for_a_suspended_jurisdiction_rejected
        """
        ridge = create_ridge()
        cycle = create_plan_cycle(required_session_count=0)
        suspended = patch_jurisdiction(ridge["id"], status="SUSPENDED")
        payload = project_payload(cycle["id"], ridge["id"], name="Ridge Levee Raise")
        sponsor = make_project_sponsor_headers(ridge["id"])

        refused = api_client.create_project(payload, sponsor)
        validate_error(refused, ApiErrorId.ERR_JURISDICTION_NOT_ACTIVE.value, 409)
        assert_fields(suspended, {"status": "SUSPENDED", "version": 2}, "the suspended member")
        _rows, meta = validate_paginated(
            api_client.list_projects(ADMIN(), params={"plan_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the refused proposal must write nothing, but the cycle reported {meta['total_count']}"
        )

        patch_jurisdiction(ridge["id"], status="ACTIVE")
        accepted = api_client.create_project(payload, sponsor)

        assert_fields(
            validate_success(accepted, 201),
            {
                "name": "Ridge Levee Raise",
                "jurisdiction_id": ridge["id"],
                "screening_status": "PROPOSED",
                "analysis_status": "NOT_ANALYZED",
                "program_status": "UNPROGRAMMED",
                "implementation_status": "NOT_STARTED",
            },
            "the proposal the reinstatement admitted",
        )


class TestAllocationGuardOrder:
    """The project-cost ceiling is read before the program's remaining funds."""

    def test_breaking_both_ceilings_reports_the_project_cost_one(self):
        """60000000 reports the cost rule; 40000000 then reports the funds rule.

        PRD 3.7 pins the order: "6. `allocated_cents` may not exceed the project's
        `total_program_cost_cents`, or `ERR_ALLOCATION_EXCEEDS_PROJECT_COST` (HTTP 422). 7.
        `allocated_cents` may not exceed the program's current `available_cents`, or
        `ERR_PROGRAM_FUNDS_EXCEEDED`."  PRD 2.5 makes the first violated rule decisive:
        "Rules are evaluated in ascending priority order, and the **first** violated rule
        short-circuits the request: its error is returned and nothing at all is written, not
        even partially."

        Design: Corner/validations/allocation_cost_check_precedes_the_available_funds_check_rejected
        """
        context = certified_levee_context()
        project_id = context["project"]["id"]
        program = create_capital_program(authorized_cents=30000000)

        both_broken = api_client.allocate(
            program["id"], allocation_payload(project_id, 60000000, 1), ADMIN()
        )
        validate_error(both_broken, ApiErrorId.ERR_ALLOCATION_EXCEEDS_PROJECT_COST.value, 422)

        only_funds_broken = api_client.allocate(
            program["id"], allocation_payload(project_id, 40000000, 1), ADMIN()
        )

        validate_error(only_funds_broken, ApiErrorId.ERR_PROGRAM_FUNDS_EXCEEDED.value, 409)
        assert_fields(
            read_project(project_id),
            {"program_status": "UNPROGRAMMED", "allocated_cents": 0, "total_program_cost_cents": 51273600},
            "the project neither attempt funded",
        )
        assert_fields(
            read_capital_program(program["id"]),
            {"committed_cents": 0, "available_cents": 30000000, "version": 1},
            "the program neither attempt touched",
        )


class TestIndicatorDefinitionGate:
    """Reporting delivery needs an indicator definition on the project row."""

    def test_an_awarded_project_without_an_indicator_refuses_reports(self):
        """The missing definition is a state error on the project, not a payload error.

        PRD 3.7: "Two conditions guard it, in this order: the project's `program_status`
        must be `AWARDED`, or `ERR_PROJECT_NOT_PROGRAMMED`; and both `indicator_code` and
        `indicator_target_value` must be non-null on the project, or
        `ERR_INDICATOR_NOT_DEFINED` — a project created without an indicator definition must
        have one added by amendment before any report can be filed, and amendment is only
        possible while the project is still `UNPROGRAMMED`, so in practice the indicator must
        be defined early."

        Design: Corner/validations/indicator_report_for_a_project_without_an_indicator_rejected
        """
        context = certified_levee_context()
        harbor_id = context["harbor"]["id"]
        project_id = context["project"]["id"]
        program = create_capital_program(authorized_cents=100000000)
        allocate(program["id"], project_id, 51273600)
        submit_grant(project_id, harbor_id)
        awarded = award_grant(project_id)

        response = api_client.report_indicator(
            project_id,
            indicator_report_payload(90.00),
            make_project_sponsor_headers(harbor_id),
        )

        validate_error(response, ApiErrorId.ERR_INDICATOR_NOT_DEFINED.value, 409)
        assert_fields(
            awarded,
            {"program_status": "AWARDED", "implementation_status": "NOT_STARTED"},
            "the awarded project with no indicator to report against",
        )
        stored = read_project(project_id)
        assert_fields(
            stored,
            {"reported_period_count": 0, "implementation_status": "NOT_STARTED"},
            "the project the refused report left alone",
        )
        assert_all_null(
            stored,
            ("indicator_code", "indicator_target_value", "indicator_latest_value",
             "indicator_attainment_pct", "latest_period_label"),
            "the project with no indicator definition",
        )


class TestScoreDomainShape:
    """The social vulnerability score lives in the closed unit interval."""

    def test_a_score_above_one_is_refused_and_exactly_one_is_admitted(self):
        """1.4 fails the shape rung while 1.00 is the top of the admitted range.

        PRD 2.5: "Every write endpoint validates its payload shape and rejects a violation
        with `ERR_INVALID_REQUEST` (HTTP 422). All required input fields must be present;
        every enum-valued field must carry a declared member of its enumeration; every
        decimal score whose domain is zero through one must lie inside that range".  PRD 3.1
        declares that domain closed: "`svi_score` is a decimal with 2 fractional digits
        between 0.00 and 1.00 inclusive."

        Design: Corner/validations/svi_score_outside_the_unit_interval_rejected
        """
        refused = api_client.create_jurisdiction(
            jurisdiction_payload(
                name="Out Of Range", jurisdiction_code="OUT-RANGE", population=1000, svi_score=1.4
            ),
            ADMIN(),
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
        _rows, meta = validate_paginated(api_client.list_jurisdictions(ADMIN()))
        assert meta["total_count"] == 0, (
            f"the refused admission must write nothing, but the register reported {meta['total_count']}"
        )

        accepted = api_client.create_jurisdiction(
            jurisdiction_payload(
                name="Top Of Range", jurisdiction_code="TOP-RANGE", population=1000, svi_score=1.00
            ),
            ADMIN(),
        )

        assert_fields(
            validate_success(accepted, 201),
            {"svi_score": 1.00, "svi_tier": "SEVERE", "disadvantaged_flag": True},
            "the member sitting on the ceiling of the range",
        )


class TestReferenceResolutionOrder:
    """Path identifiers resolve first, then body references, then domain state."""

    def test_the_unknown_path_id_is_reported_before_the_unknown_body_id(self):
        """Both identifiers are unknown, and the cycle in the path decides the error.

        PRD 2.5: "Every identifier embedded in the URL must resolve to an existing row, and
        they are checked in the order they appear in the path from left to right, so on a
        nested path the leftmost unresolved identifier decides the error."  Only after that
        rung does PRD 2.5 read the body: "Every foreign reference carried in a request
        payload must resolve, checked in the order the endpoint declares its input fields,
        using the same identifier-to-code map as the path check."

        Design: Corner/validations/path_ids_resolve_left_to_right_before_body_keys_not_found
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=0)
        delegate = make_jurisdiction_delegate_headers(harbor["id"])
        unknown_body = endorsement_payload(NON_EXISTENT_UUID, decision="ENDORSED")

        unknown_path = api_client.cast_endorsement(NON_EXISTENT_UUID, unknown_body, delegate)
        validate_error(unknown_path, ApiErrorId.ERR_PLAN_CYCLE_NOT_FOUND.value, 404)

        repaired_path = api_client.cast_endorsement(cycle["id"], unknown_body, delegate)

        validate_error(repaired_path, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value, 404)
        _rows, meta = validate_paginated(api_client.list_endorsements(ADMIN()))
        assert meta["total_count"] == 0, (
            f"neither refusal may write an endorsement, but the collection reported {meta['total_count']}"
        )

    def test_an_unknown_body_jurisdiction_beats_the_plan_cycle_state_gate(self):
        """The cycle is already past proposals, and the 404 still wins over the 409.

        PRD 2.5 places body reference resolution at rung five and every domain rule below
        it: "Everything from priority 9 downwards is domain logic: jurisdiction standing,
        plan-cycle state, publication state, freshness state, concurrency, segregation of
        duties, equity floors, graph acyclicity, uniqueness, cross-entity readiness,
        arithmetic sanity, temporal occupancy and fiscal capacity — in that broad order."
        The state gate itself is PRD 3.5's: "The named plan cycle must be in `DRAFT`,
        `ENGAGEMENT` or `REVISION` — a cycle already in `ENDORSEMENT_ROUND`, `ADOPTED` or
        `FAILED` accepts no new projects and yields `ERR_PLAN_CYCLE_STATE_INVALID`."

        Design: Corner/validations/body_foreign_keys_resolve_before_the_plan_cycle_state_gate_returns_404
        """
        harbor = create_harbor()
        cycle = _cycle_at_endorsement_round(harbor["id"])
        sponsor = make_project_sponsor_headers(harbor["id"])

        unknown_member = api_client.create_project(
            project_payload(cycle["id"], NON_EXISTENT_UUID, name="Ghost Sponsor Levee"), sponsor
        )
        validate_error(unknown_member, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value, 404)

        known_member = api_client.create_project(
            project_payload(cycle["id"], harbor["id"], name="Late Levee"), sponsor
        )

        validate_error(known_member, ApiErrorId.ERR_PLAN_CYCLE_STATE_INVALID.value, 409)
        assert_fields(
            read_plan_cycle(cycle["id"]),
            {"status": "ENDORSEMENT_ROUND", "round_number": 1},
            "the cycle that accepted neither proposal",
        )
        _rows, meta = validate_paginated(
            api_client.list_projects(ADMIN(), params={"plan_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 1, (
            "only the screened project that opened the round may exist, but the cycle "
            f"reported {meta['total_count']} projects"
        )
