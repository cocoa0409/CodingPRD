"""Endpoint side effects: assembled digests, filtered pages and partial updates."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    PROVIDER_ADMIN,
    admit_panelist,
    admit_registrar,
    api_client,
    assert_domain,
    assert_panelist,
    assert_precedent_entry,
    assert_vote,
    build_docket,
    cast_seat_vote,
    draft_decision,
    file_complaint,
    get_success_data,
    issue_decision,
    make_panelist_headers,
    make_registrar_headers,
    publish_payload,
    read_case,
    read_decision,
    read_domain,
    read_panelist,
    register_domain,
    run_sweep,
    set_availability,
    set_clock,
    set_domain_lock,
    setup_single_member_panel,
    validate_error,
    validate_paginated,
)

PUB_DOCKET = {
    "iana_id": "IANA-9031",
    "domain_name": "pub.example",
    "legal_name": "Pub Ltd",
    "country_code": "GB",
    "registrar_name": "Pub Registrar",
}
QUIET_DOCKET = {
    "iana_id": "IANA-9032",
    "domain_name": "quiet.example",
    "legal_name": "Quiet Ltd",
    "country_code": "GB",
    "registrar_name": "Quiet Registrar",
}


class TestPublicationDigestAndPrecedentFilters:
    def _issued_transfer_decision(self):
        bundle = setup_single_member_panel(
            panelist_overrides={
                "roster_admitted_at": "2019-04-01T00:00:00Z",
                "firm_name": "Bauer Legal",
                "specializations": ["TRADEMARK"],
                "max_overlapping_engagements": 3,
            },
            **PUB_DOCKET
        )
        panelist = bundle["panelists"][0]
        decision = draft_decision(
            bundle["case"]["id"], panelist["id"],
            draft_summary="The mark is identical and the registration was made in bad faith.",
        )
        cast_seat_vote(
            decision["id"], panelist["id"], "SOLE", "TRANSFER",
            rdnh_vote=False, rationale="Transfer ordered.",
        )
        bundle["decision"] = issue_decision(decision["id"])
        bundle["case"] = read_case(bundle["case"]["id"])
        return bundle

    def test_the_stored_digest_is_assembled_by_the_server_and_the_caller_text_is_discarded(self):
        """PRD §3.9: "An optional `digest_text` may be supplied, but the digest
        actually stored is assembled by the server at publication from the case's
        `case_number`, then the decision's `outcome`, then the literal text `rdnh=`
        followed by the decision's `rdnh_finding`, with those three parts joined by a
        space-pipe-space separator."
        PRD §3.9: "A redaction level of `NONE` drives `publication_status` to
        `PUBLISHED`; either `PARTY_NAMES` or `FULL` drives it to `REDACTED`."
        PRD §3.9: "Exactly one precedent entry exists per decision, created with
        `published_at` stamped from the clock, the supplied `redaction_level` and
        `precedent_tags`, `superseded` false, and `citable` true unless the redaction
        level was `FULL`."

        Design: Corner/endpoints/publication_assembles_its_own_digest_and_the_precedent_filters_narrow_the_page
        """
        bundle = self._issued_transfer_decision()
        decision = bundle["decision"]
        assert decision["outcome"] == "TRANSFER"
        assert decision["rdnh_finding"] is False
        assert decision["publication_status"] == "UNPUBLISHED"
        case_number = bundle["case"]["case_number"]

        entry = get_success_data(
            api_client.publish_decision(
                decision["id"],
                publish_payload(
                    "PARTY_NAMES",
                    precedent_tags=["identical-mark", "offer-for-sale"],
                    digest_text="CALLER SUPPLIED DIGEST THAT MUST BE DISCARDED",
                ),
                PROVIDER_ADMIN,
            ),
            201,
        )
        assert_precedent_entry(entry)
        assert entry["decision_id"] == decision["id"]
        assert entry["published_at"] == "2026-08-01T00:00:00.000Z"
        assert entry["redaction_level"] == "PARTY_NAMES"
        assert entry["precedent_tags"] == ["identical-mark", "offer-for-sale"]
        assert entry["digest_text"] == "%s | TRANSFER | rdnh=false" % case_number
        assert entry["superseded"] is False
        assert entry["citable"] is True, "only a FULL redaction costs an entry its citability"
        assert entry["citation_count"] == 0
        assert float(entry["precedent_weight"]) == 0.00

        published = read_decision(decision["id"])
        assert published["publication_status"] == "REDACTED"
        assert published["status"] == "ISSUED", (
            "publication runs on its own dimension and never touches enforcement"
        )

    def test_the_search_filters_read_the_outcome_and_the_total_ignores_the_window(self):
        """PRD §3.9: "The precedent database is searched with three optional filters
        plus pagination: `outcome`, restricting to decisions with that operative
        outcome; `citable`, restricting to entries currently citable; and
        `include_superseded`, which defaults to false."
        PRD §2.3: "`total_count` counts the rows that satisfy the request's filters
        before pagination is applied, and `has_more` is true when rows remain beyond
        the returned window."
        PRD §3.9: "Both figures are re-evaluated on every read of the entry and on
        every precedent search, against the clock as it reads at that moment —
        advancing the clock alone changes the reported weight with no write anywhere."
        PRD §3.7: "Ballots are immutable once written and no seat may ballot twice on
        the same decision — a second attempt is refused with
        `ERR_VOTE_ALREADY_CAST`."

        Design: Corner/endpoints/publication_assembles_its_own_digest_and_the_precedent_filters_narrow_the_page
        """
        bundle = self._issued_transfer_decision()
        decision_id = bundle["decision"]["id"]
        panelist_id = bundle["panelists"][0]["id"]
        panelist_headers = make_panelist_headers(panelist_id)
        entry = get_success_data(
            api_client.publish_decision(
                decision_id,
                publish_payload(
                    "PARTY_NAMES", precedent_tags=["identical-mark", "offer-for-sale"]
                ),
                PROVIDER_ADMIN,
            ),
            201,
        )

        citable_rows, citable_meta = validate_paginated(
            api_client.search_precedents(
                panelist_headers, params={"citable": True, "limit": 1, "offset": 0}
            )
        )
        assert citable_meta["total_count"] == 1
        assert citable_meta["has_more"] is False
        assert citable_rows[0]["decision_id"] == decision_id
        assert citable_rows[0]["precedent_tags"] == ["identical-mark", "offer-for-sale"]

        cancel_rows, cancel_meta = validate_paginated(
            api_client.search_precedents(
                panelist_headers,
                params={"outcome": "CANCELLATION", "limit": 10, "offset": 0},
            )
        )
        assert cancel_meta["total_count"] == 0
        assert cancel_rows == [], "the filter reads the decision's outcome, not the tags"

        past_rows, past_meta = validate_paginated(
            api_client.search_precedents(
                CASE_MANAGER,
                params={
                    "outcome": "TRANSFER",
                    "include_superseded": False,
                    "limit": 10,
                    "offset": 1,
                },
            )
        )
        assert past_meta["total_count"] == 1, "the total counts matches, not the window"
        assert past_meta["has_more"] is False
        assert past_rows == []

        reread = get_success_data(api_client.get_precedent_entry(decision_id, PROVIDER_ADMIN))
        assert len(reread) == 1
        assert reread[0]["digest_text"] == entry["digest_text"]
        assert float(reread[0]["precedent_weight"]) == 0.00

        ballots, ballot_meta = validate_paginated(
            api_client.list_votes(decision_id, panelist_headers, params={"limit": 10, "offset": 0})
        )
        assert ballot_meta["total_count"] == 1, (
            "publication redacts the precedent entry, never the underlying ballots"
        )
        assert_vote(ballots[0])
        assert ballots[0]["seat"] == "SOLE"
        assert ballots[0]["vote"] == "TRANSFER"
        assert ballots[0]["rdnh_vote"] is False
        assert ballots[0]["voter_panelist_id"] == panelist_id
        assert ballots[0]["rationale"] == "Transfer ordered."


class TestQuietSweep:
    def test_a_case_on_no_deadline_clock_leaves_every_counter_at_zero_a_month_later(self):
        """PRD §2.4: "The sweep reports what it did as four counters in its response
        body: `expired_notice_count`, `overdue_verification_count`,
        `defaulted_case_count` and `closed_case_count`."
        PRD §2.4: "It is idempotent — running it twice at the same clock reading
        changes nothing on the second pass and returns all four counters as zero."
        PRD §3.2: "An accepted filing lands in `status` `FILED` with `version` 1,
        mints its `case_number`, and sets `respondent_panel_election` to `NONE`."

        Design: Corner/endpoints/deadline_sweep_reports_all_zero_counters_when_nothing_is_due
        """
        docket = build_docket(**QUIET_DOCKET)
        case = file_complaint(docket["complainant"], docket["domain"])
        assert case["status"] == "FILED"
        assert case["version"] == 1
        assert case["default_recorded"] is False

        counters = ["expired_notice_count", "overdue_verification_count",
                    "defaulted_case_count", "closed_case_count"]
        first = run_sweep()
        assert [first[name] for name in counters] == [0, 0, 0, 0], (
            "a FILED case has no OPEN notice, no REQUESTED verification and no response window"
        )

        set_clock("2026-09-01T00:00:00Z")
        second = run_sweep()
        assert [second[name] for name in counters] == [0, 0, 0, 0]

        quiet = read_case(case["id"])
        assert quiet["status"] == "FILED"
        assert quiet["default_recorded"] is False
        assert quiet["version"] == case["version"], "a no-op sweep writes nothing at all"
        assert quiet["closed_at"] is None
        assert quiet["response_due_at"] is None


class TestAvailabilityPartialUpdate:
    def _rostered_panelist(self):
        panelist = admit_panelist(
            full_name="Marta Kowalska", nationality_code="PL",
            roster_admitted_at="2021-02-01T00:00:00Z", max_overlapping_engagements=3,
        )
        assert_panelist(panelist)
        assert panelist["status"] == "AVAILABLE"
        assert panelist["max_overlapping_engagements"] == 3
        assert panelist["unavailable_from"] is None
        assert panelist["unavailable_to"] is None
        assert panelist["active_case_load"] == 0
        return panelist

    def test_each_subset_of_attributes_moves_only_itself(self):
        """PRD §3.1: "A panelist's own availability can be revised later, either by
        the neutral or by a provider administrator, in a single call that carries any
        subset of four attributes: `status`, which may be `AVAILABLE`, `UNAVAILABLE`
        or `SUSPENDED`; `unavailable_from` and `unavailable_to`, the inclusive start
        and inclusive end of a declared blackout window; and
        `max_overlapping_engagements`."
        PRD §3.1: "Any attribute omitted from the call is left exactly as it was, and
        supplying `unavailable_from` as null clears the declared blackout interval
        entirely."

        Design: Corner/endpoints/availability_patch_leaves_omitted_fields_alone_and_a_null_clears_the_blackout
        """
        panelist = self._rostered_panelist()
        panelist_id = panelist["id"]

        raised = set_availability(panelist_id, max_overlapping_engagements=6)
        assert raised["max_overlapping_engagements"] == 6
        assert raised["status"] == "AVAILABLE"
        assert raised["unavailable_from"] is None
        assert raised["unavailable_to"] is None

        blacked_out = set_availability(
            panelist_id, headers=make_panelist_headers(panelist_id),
            unavailable_from="2026-09-10T00:00:00Z",
            unavailable_to="2026-09-20T00:00:00Z",
        )
        assert blacked_out["unavailable_from"] == "2026-09-10T00:00:00Z"
        assert blacked_out["unavailable_to"] == "2026-09-20T00:00:00Z"
        assert blacked_out["max_overlapping_engagements"] == 6

        stood_down = set_availability(panelist_id, status="UNAVAILABLE")
        assert stood_down["status"] == "UNAVAILABLE"
        assert stood_down["max_overlapping_engagements"] == 6
        assert stood_down["unavailable_from"] == "2026-09-10T00:00:00Z"
        assert stood_down["unavailable_to"] == "2026-09-20T00:00:00Z"

    def test_an_out_of_range_ceiling_and_an_undeclared_status_are_both_refused(self):
        """PRD §3.1: "and `max_overlapping_engagements`, the aggregate ceiling on
        engagement windows that may overlap a new candidate window on that neutral,
        which defaults to 5 and must be between 1 and 20."
        PRD §3.1: "Any attribute omitted from the call is left exactly as it was, and
        supplying `unavailable_from` as null clears the declared blackout interval
        entirely."

        Design: Corner/endpoints/availability_patch_leaves_omitted_fields_alone_and_a_null_clears_the_blackout
        """
        panelist = self._rostered_panelist()
        panelist_id = panelist["id"]
        set_availability(panelist_id, max_overlapping_engagements=6)
        set_availability(
            panelist_id, unavailable_from="2026-09-10T00:00:00Z",
            unavailable_to="2026-09-20T00:00:00Z",
        )
        set_availability(panelist_id, status="UNAVAILABLE")

        over_ceiling = api_client.set_panelist_availability(
            panelist_id, {"max_overlapping_engagements": 21}, PROVIDER_ADMIN
        )
        validate_error(over_ceiling, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        assert read_panelist(panelist_id)["max_overlapping_engagements"] == 6

        undeclared = api_client.set_panelist_availability(
            panelist_id, {"status": "RETIRED"}, PROVIDER_ADMIN
        )
        validate_error(undeclared, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        assert read_panelist(panelist_id)["status"] == "UNAVAILABLE"

        cleared = set_availability(panelist_id, status="AVAILABLE", unavailable_from=None)
        assert cleared["status"] == "AVAILABLE"
        assert cleared["unavailable_from"] is None
        assert cleared["unavailable_to"] is None, (
            "a null on the start clears the whole declared interval"
        )
        assert cleared["max_overlapping_engagements"] == 6


class TestManualLockCycle:
    def test_the_operator_surface_writes_and_clears_locked_at_symmetrically(self):
        """PRD §3.1: "A newly registered domain starts at `lock_status` `UNLOCKED`
        with both `locked_at` and `executed_at` null."
        PRD §3.1: "Applying the lock records `locked_at` at the current logical-clock
        instant; releasing it returns `locked_at` to null. Either way the domain's
        `version` advances."

        Design: Corner/endpoints/manual_lock_cycles_the_domain_and_refuses_an_undeclared_lock_status
        """
        registrar = admit_registrar(iana_id="IANA-9033", name="Lockcycle Registrar")
        domain = register_domain(registrar["id"], "lockcycle.example")
        assert_domain(domain)
        assert domain["lock_status"] == "UNLOCKED"
        assert domain["locked_at"] is None
        assert domain["executed_at"] is None

        locked = set_domain_lock(
            domain["id"], "LOCKED", make_registrar_headers(registrar["id"])
        )
        assert locked["lock_status"] == "LOCKED"
        assert locked["locked_at"] == "2026-08-01T00:00:00.000Z"
        assert locked["version"] > domain["version"]

        set_clock("2026-08-02T00:00:00Z")
        released = set_domain_lock(domain["id"], "UNLOCKED")
        assert released["lock_status"] == "UNLOCKED"
        assert released["locked_at"] is None
        assert released["version"] > locked["version"]
        assert released["executed_at"] is None

    def test_neither_an_unknown_value_nor_an_executed_state_is_accepted_here(self):
        """PRD §3.1: "It accepts a `lock_status` of either `UNLOCKED` or `LOCKED`; any
        other value, and any attempt to touch a domain whose current `lock_status` is
        `TRANSFER_EXECUTED` or `CANCELLATION_EXECUTED`, is refused with
        `ERR_INVALID_REQUEST`."
        PRD §3.1: "Applying the lock records `locked_at` at the current logical-clock
        instant; releasing it returns `locked_at` to null. Either way the domain's
        `version` advances."

        Design: Corner/endpoints/manual_lock_cycles_the_domain_and_refuses_an_undeclared_lock_status
        """
        registrar = admit_registrar(iana_id="IANA-9033", name="Lockcycle Registrar")
        domain = register_domain(registrar["id"], "lockcycle.example")
        set_domain_lock(domain["id"], "LOCKED", make_registrar_headers(registrar["id"]))
        set_clock("2026-08-02T00:00:00Z")
        released = set_domain_lock(domain["id"], "UNLOCKED")

        unknown = api_client.set_domain_lock(
            domain["id"], {"lock_status": "FROZEN"}, PROVIDER_ADMIN
        )
        validate_error(unknown, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        executed = api_client.set_domain_lock(
            domain["id"], {"lock_status": "TRANSFER_EXECUTED"}, PROVIDER_ADMIN
        )
        validate_error(executed, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        final = read_domain(domain["id"])
        assert final["lock_status"] == "UNLOCKED"
        assert final["locked_at"] is None
        assert final["version"] == released["version"], "neither refusal wrote anything"
        assert final["updated_at"] == released["updated_at"]
