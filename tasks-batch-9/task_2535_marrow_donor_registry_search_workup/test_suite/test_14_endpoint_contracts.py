"""Endpoint contract behaviour: the observable shape of one call's effects.

Each test here walks one endpoint of the marrow-donor programme and pins what
the PRD says that single call must leave behind — the version it bumps, the rows
it links, the cascade it fires and the counters it re-derives — rather than the
arithmetic of any one field.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assertions,
    constants,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value: str) -> datetime:
    """An instant-valued field parsed for exact-to-the-second comparison (§2.4)."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_registry_update_bumps_the_version_and_binds_only_later_typing_requests(
    api, operations_headers, coordinator_headers
):
    """A partial registry PATCH versions the row and rebinds only future deadlines.

    PRD §3.1: "An operations update may adjust `cooperation_status`,
    `cooperation_tier`, `fx_rate_to_usd` or `ct_response_deadline_hours`, each
    optionally, and each such update increments the registry's `version` by one."
    PRD §3.1: "And a new `ct_response_deadline_hours` applies only to typing
    requests raised after the change; deadlines already computed are frozen."
    PRD §3.4: "The deadline is computed once, at request time, and then frozen."
    PRD §3.4: "It begins at `requested_at` plus the donor registry's contractual
    `ct_response_deadline_hours`."
    PRD §2.10: "`Registry.donor_count` is the count of donor profiles whose
    `registry_id` is that registry, counted regardless of their
    `availability_status`."

    Design: Corner/endpoints/a_partial_registry_update_bumps_the_version_and_binds_only_later_requests
    """
    ctx = fixtures.setup_primary_candidate(
        num_donors=2,
        with_center=False,
        registry_overrides={"cooperation_tier": 1, "ct_response_deadline_hours": 168},
    )
    created = ctx["registry"]
    assert created["version"] == 1, "a freshly registered registry opens at version 1"
    assert created["cooperation_tier"] == 1
    assert created["ct_response_deadline_hours"] == 168

    before = validate_success(api.get_registry(created["id"], operations_headers))
    assert before["donor_count"] == 2, "donor_count re-derives over the two enrolled donors"

    primary = fixtures.candidate_by_rank(ctx, 1)
    backup = fixtures.candidate_by_rank(ctx, 2)

    early = validate_success(
        api.create_typing_request(
            primary["id"], f.create_typing_request_payload(), coordinator_headers
        ),
        expected_status=201,
    )
    assert _instant(early["requested_at"]) == _instant(constants.CLOCK_EPOCH)
    assert _instant(early["deadline_at"]) == _instant("2026-08-08T00:00:00Z")

    patched = validate_success(
        api.update_registry(
            created["id"], {"ct_response_deadline_hours": 240}, operations_headers
        )
    )
    assertions.assert_registry(patched)
    assert patched["version"] == 2, "the partial update increments version by exactly one"
    assert patched["ct_response_deadline_hours"] == 240
    assert patched["cooperation_tier"] == 1, "an omitted field is left untouched"
    assert patched["code"] == created["code"]
    assert patched["name"] == created["name"]
    assert patched["currency_code"] == created["currency_code"]
    assert float(patched["fx_rate_to_usd"]) == float(created["fx_rate_to_usd"])
    assert patched["is_domestic"] == created["is_domestic"]
    assert patched["cooperation_status"] == created["cooperation_status"]

    late = validate_success(
        api.create_typing_request(
            backup["id"], f.create_typing_request_payload(), coordinator_headers
        ),
        expected_status=201,
    )
    assert _instant(late["deadline_at"]) == _instant("2026-08-11T00:00:00Z"), (
        "a request raised after the change takes the new contractual hours"
    )

    rows, _meta = validate_paginated(
        api.list_typing_requests(primary["id"], coordinator_headers)
    )
    assert len(rows) == 1
    assert _instant(rows[0]["deadline_at"]) == _instant("2026-08-08T00:00:00Z"), (
        "the deadline computed before the change is frozen"
    )

    retiered = validate_success(
        api.update_registry(created["id"], {"cooperation_tier": 2}, operations_headers)
    )
    assert retiered["version"] == 3
    assert retiered["cooperation_tier"] == 2
    assert retiered["ct_response_deadline_hours"] == 240


def test_screening_refuses_an_outcome_that_disagrees_with_its_deferral_class(api):
    """DEFER must arrive with TEMPORARY and a future date, and a refusal writes nothing.

    PRD §3.5: "The three outcomes must agree with their deferral class, and a
    disagreement is refused with `ERR_SCREENING_OUTCOME_MISMATCH`."
    PRD §3.5: "An `outcome` of `DEFER` requires `deferral_type` `TEMPORARY`
    together with a `deferral_until` that is strictly later than the current
    logical UTC date."

    Design: Corner/endpoints/the_screening_action_defers_the_donor_and_enforces_its_outcome_pairing
    """
    ctx = fixtures.setup_pipeline("typing_responded", num_donors=1, with_center=False)

    wrong_class = api.record_screening(
        ctx["candidate_id"],
        f.screening_payload(outcome="DEFER", deferral_type="NONE"),
        ctx["liaison_headers"],
    )
    validate_error(wrong_class, ApiErrorId.ERR_SCREENING_OUTCOME_MISMATCH.value)

    past_date = api.record_screening(
        ctx["candidate_id"],
        f.screening_payload(
            outcome="DEFER", deferral_type="TEMPORARY", deferral_until="2026-07-01"
        ),
        ctx["liaison_headers"],
    )
    validate_error(past_date, ApiErrorId.ERR_SCREENING_OUTCOME_MISMATCH.value)

    donor = validate_success(api.get_donor(ctx["donor_id"], ctx["liaison_headers"]))
    assert donor["availability_status"] == "AVAILABLE", "a refused screening defers nobody"
    assert donor["blocked_day_count"] == 0, "a refused screening blocks no calendar day"
    assert donor["deferral_until"] is None

    candidate = validate_success(
        api.get_match_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert candidate["status"] == "TYPING_RESPONDED"


def test_screening_deferral_blocks_the_donor_calendar_through_the_deferral_date(api):
    """An accepted DEFER defers the donor and blocks 46 inclusive calendar days.

    PRD §3.5: "A deferring screening moves the candidate `TYPING_RESPONDED →
    DEFERRED` and moves the donor `AVAILABLE → TEMPORARILY_DEFERRED`."
    PRD §3.5: "The supplied `deferral_until` is written onto the donor, and the
    system creates an `ACTIVE` calendar window for that donor with `reason`
    `DEFERRAL`, spanning the current logical UTC date through `deferral_until`
    inclusive, which raises the donor's `blocked_day_count` by that window's
    `day_count`."
    PRD §3.2: "Otherwise the server computes `day_count` as the number of
    calendar days in the closed interval — the difference between the two dates
    plus one, so a window whose two dates are equal has a day count of one — and
    adds that count to the donor's `blocked_day_count`."
    PRD §2.10: "`SearchRequest.backup_candidate_count` is the count of that
    search's candidates whose `candidate_role` is `BACKUP` and whose `status` is
    one of `IDENTIFIED`, `TYPING_REQUESTED`, `TYPING_RESPONDED` or
    `SCREENING_PASSED`."

    Design: Corner/endpoints/the_screening_action_defers_the_donor_and_enforces_its_outcome_pairing
    """
    ctx = fixtures.setup_pipeline("typing_responded", num_donors=1, with_center=False)

    candidate = validate_success(
        api.record_screening(
            ctx["candidate_id"],
            f.screening_payload(
                outcome="DEFER", deferral_type="TEMPORARY", deferral_until="2026-09-15"
            ),
            ctx["liaison_headers"],
        )
    )
    assert candidate["status"] == "DEFERRED"
    assert candidate["screening_outcome"] == "DEFER"
    assert candidate["screening_deferral_type"] == "TEMPORARY"

    donor = validate_success(api.get_donor(ctx["donor_id"], ctx["liaison_headers"]))
    assert donor["availability_status"] == "TEMPORARILY_DEFERRED"
    assert donor["deferral_until"] == "2026-09-15"
    assert donor["blocked_day_count"] == 46

    windows, meta = validate_paginated(
        api.list_unavailability_windows(ctx["donor_id"], ctx["liaison_headers"])
    )
    assert meta["total_count"] == 1, "the deferral creates exactly one calendar window"
    window = windows[0]
    assertions.assert_unavailability_window(window)
    assert window["reason"] == "DEFERRAL"
    assert window["status"] == "ACTIVE"
    assert window["date_from"] == "2026-08-01"
    assert window["date_to"] == "2026-09-15"
    assert window["day_count"] == 46
    assert window["source_booking_id"] is None

    search = validate_success(
        api.get_search_request(ctx["search_id"], ctx["coordinator_headers"])
    )
    assert search["backup_candidate_count"] == 0, (
        "a single-donor pool has no backup to count, before or after the deferral"
    )


SWEEP_AT = "2026-08-08T00:00:01Z"


def _search_with_two_overdue_typing_requests():
    """Two candidates of one search, each holding a REQUESTED row one second overdue."""
    ctx = fixtures.setup_primary_candidate(num_donors=2, with_center=False)
    for rank_position in (1, 2):
        fixtures.advance_to_typing_requested(
            ctx, fixtures.candidate_by_rank(ctx, rank_position)["id"]
        )
    fixtures.set_clock(SWEEP_AT)
    return ctx


def _sole_typing_request(api, candidate_id, headers):
    rows, _meta = validate_paginated(api.list_typing_requests(candidate_id, headers))
    assert len(rows) == 1, f"expected exactly one typing request, got {len(rows)}"
    return rows[0]


def test_one_sweep_expires_every_overdue_request_of_the_search(api, operations_headers):
    """A single sweep call walks and expires both overdue rows, not just the first.

    PRD §3.4: "A `RegistryOperations` operator sweeps a search, and the sweep
    walks that search's typing requests that are still in `REQUESTED` status in
    `created_at` ascending order."
    PRD §3.4: "For each of them, the current logical instant is compared against
    `deadline_at` with a strict test: only a request whose deadline lies strictly
    before the current instant expires."
    PRD §3.4: "An expiring request moves `REQUESTED → EXPIRED`, has
    `expired_by_sweep_at` stamped with the sweep instant, and drags its candidate
    `TYPING_REQUESTED → TYPING_EXPIRED`."
    PRD §3.4: "Every sweep stamps the search's `last_sweep_at` with the sweep
    instant, whether or not anything expired."
    PRD §3.3: "Because ranking is a one-time act, `rank_position` is frozen at
    materialisation and is never recomputed afterwards — not when a donor is
    deferred, not when a backup is promoted, not when the pool shrinks."

    Design: Corner/endpoints/one_sweep_call_processes_every_overdue_row_of_the_search
    """
    ctx = _search_with_two_overdue_typing_requests()
    coordinator = ctx["coordinator_headers"]

    search = validate_success(
        api.run_deadline_sweep(ctx["search_id"], operations_headers)
    )
    assert _instant(search["last_sweep_at"]) == _instant(SWEEP_AT)

    for rank_position, expected_role in ((1, "PRIMARY"), (2, "BACKUP")):
        candidate_id = fixtures.candidate_by_rank(ctx, rank_position)["id"]
        request = _sole_typing_request(api, candidate_id, coordinator)
        assert request["status"] == "EXPIRED", (
            f"the rank-{rank_position} candidate's overdue request must expire in the same sweep"
        )
        assert _instant(request["expired_by_sweep_at"]) == _instant(SWEEP_AT)

        candidate = validate_success(api.get_match_candidate(candidate_id, coordinator))
        assert candidate["status"] == "TYPING_EXPIRED"
        assert candidate["ct_attempt_count"] == 1
        assert candidate["candidate_role"] == expected_role
        assert candidate["rank_position"] == rank_position


def test_a_second_sweep_at_the_same_instant_changes_nothing(api, operations_headers):
    """Re-sweeping finds no REQUESTED rows left and re-stamps the same instant.

    PRD §3.4: "A `RegistryOperations` operator sweeps a search, and the sweep
    walks that search's typing requests that are still in `REQUESTED` status in
    `created_at` ascending order."
    PRD §3.4: "Every sweep stamps the search's `last_sweep_at` with the sweep
    instant, whether or not anything expired."

    Design: Corner/endpoints/one_sweep_call_processes_every_overdue_row_of_the_search
    """
    ctx = _search_with_two_overdue_typing_requests()
    coordinator = ctx["coordinator_headers"]
    validate_success(api.run_deadline_sweep(ctx["search_id"], operations_headers))

    first_pass = [
        _sole_typing_request(api, fixtures.candidate_by_rank(ctx, rank)["id"], coordinator)
        for rank in (1, 2)
    ]

    again = validate_success(api.run_deadline_sweep(ctx["search_id"], operations_headers))
    assert _instant(again["last_sweep_at"]) == _instant(SWEEP_AT)

    for rank_position, before in zip((1, 2), first_pass):
        candidate_id = fixtures.candidate_by_rank(ctx, rank_position)["id"]
        after = _sole_typing_request(api, candidate_id, coordinator)
        assert after["status"] == "EXPIRED"
        assert _instant(after["expired_by_sweep_at"]) == _instant(
            before["expired_by_sweep_at"]
        ), "an already-expired request is not re-stamped by a later sweep"
        candidate = validate_success(api.get_match_candidate(candidate_id, coordinator))
        assert candidate["status"] == "TYPING_EXPIRED"
        assert candidate["ct_attempt_count"] == 1


def test_search_request_links_its_patient_and_its_scored_donor(api, coordinator_headers):
    """A search resolves its patient FK first, then links the candidates it wrote.

    PRD §2.8: "Opening a search resolves `patient_id`, and an unknown value
    yields `ERR_PATIENT_NOT_FOUND`."
    PRD §3.3: "Each materialised candidate records its `search_request_id`, its
    `donor_id`, the computed `preliminary_score` and `rank_score`, its frozen
    `rank_position` and its `candidate_role`, opens in `status` `IDENTIFIED` with
    `ct_attempt_count` at zero, and carries `confirmed_score`,
    `confirmed_match_grade`, `screening_outcome`, `screening_deferral_type` and
    `promoted_from_rank` all null."
    PRD §3.3: "The search's `match_pool_size` records how many candidates were
    written and `backup_candidate_count` records how many of them are backups."
    PRD §3.3: "Candidates can be listed and filtered by `search_request_id`, by
    `donor_id`, by `candidate_role` and by `status`, and a patient's searches are
    separately listable, which is how a coordinator reaches a search it did not
    record the identifier of."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of rows matching the filter before paging and `has_more`
    indicates whether rows remain beyond the returned page."

    Design: Corner/endpoints/a_search_request_links_its_patient_and_its_scored_donors
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.setup_donor_pool(ctx, num_donors=1)[0]
    patient = fixtures.create_patient(headers=coordinator_headers)

    _rows, meta = validate_paginated(
        api.list_patient_search_requests(patient["id"], coordinator_headers)
    )
    assert meta["total_count"] == 0, "the patient carries no search before the call"

    unknown = api.create_search_request(
        f.create_search_request_payload(NON_EXISTENT_UUID), coordinator_headers
    )
    validate_error(unknown, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)

    _rows, meta = validate_paginated(
        api.list_patient_search_requests(patient["id"], coordinator_headers)
    )
    assert meta["total_count"] == 0, "the refused open wrote no search row"

    search = validate_success(
        api.create_search_request(
            f.create_search_request_payload(patient["id"]), coordinator_headers
        ),
        expected_status=201,
    )
    assertions.assert_search_request(search)
    assert search["patient_id"] == patient["id"]
    assert search["status"] == "SEARCHING"
    assert search["match_pool_size"] == 1
    assert search["backup_candidate_count"] == 0

    rows, meta = validate_paginated(
        api.list_patient_search_requests(patient["id"], coordinator_headers)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [search["id"]]

    candidates, meta = validate_paginated(
        api.list_match_candidates(coordinator_headers, params={"donor_id": donor["id"]})
    )
    assert meta["total_count"] == 1, "the donor is materialised exactly once"
    candidate = candidates[0]
    assertions.assert_match_candidate(candidate)
    assert candidate["search_request_id"] == search["id"]
    assert candidate["donor_id"] == donor["id"]
    assert candidate["rank_position"] == 1
    assert candidate["candidate_role"] == "PRIMARY"
    assert candidate["status"] == "IDENTIFIED"
    assert candidate["ct_attempt_count"] == 0
    assert candidate["confirmed_score"] is None
    assert candidate["confirmed_match_grade"] is None
    assert candidate["screening_outcome"] is None
    assert candidate["screening_deferral_type"] is None
    assert candidate["promoted_from_rank"] is None


def test_donor_follow_up_counters_are_recomputed_from_the_filed_rows(
    api, physician_headers
):
    """The donor's follow-up counters are reads over its rows, never client inputs.

    PRD §3.2: "Newly registered donors start with `blocked_day_count` and
    `adverse_event_count` at zero, with `deferral_until` null and
    `last_followup_at` null, and each registration raises the owning registry's
    `donor_count` by one."
    PRD §3.9: "Each filed row stamps `reported_at` from the logical clock and
    refreshes the donor's `last_followup_at` to the latest `reported_at` on
    record."
    PRD §3.9: "An `ADVERSE_EVENT` row additionally raises the donor's
    `adverse_event_count` by one."
    PRD §3.9: "When an `ADVERSE_EVENT` row carries a `severity_grade` of 4 or
    higher, the row's `triggered_permanent_deferral` is recorded as true — it is
    false on every other row — and the donor's `availability_status` moves to
    `PERMANENTLY_DEFERRED`, whether the donor was `AVAILABLE` or already
    `TEMPORARILY_DEFERRED` at the time."
    PRD §2.3: "Unless a specific list endpoint documents a different ordering,
    list results are sorted by `created_at` ascending."

    Design: Corner/endpoints/donor_counters_are_computed_reads_not_stored_inputs
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)
    liaison = ctx["liaison_headers"]
    assert donor["adverse_event_count"] == 0
    assert donor["last_followup_at"] is None
    assert donor["availability_status"] == "AVAILABLE"

    contact = validate_success(
        api.create_follow_up(
            donor["id"],
            f.create_follow_up_payload("DAY_7_CONTACT", 0),
            liaison,
        ),
        expected_status=201,
    )
    assertions.assert_donor_follow_up(contact)
    assert contact["triggered_permanent_deferral"] is False
    assert _instant(contact["reported_at"]) == _instant(constants.CLOCK_EPOCH)

    after_contact = validate_success(api.get_donor(donor["id"], liaison))
    assert after_contact["adverse_event_count"] == 0, (
        "a scheduled contact is not an adverse event"
    )
    assert _instant(after_contact["last_followup_at"]) == _instant(constants.CLOCK_EPOCH)
    assert after_contact["availability_status"] == "AVAILABLE"

    fixtures.set_clock("2026-08-15T09:30:00Z")
    moderate = validate_success(
        api.create_follow_up(
            donor["id"],
            f.create_follow_up_payload("ADVERSE_EVENT", 3),
            physician_headers,
        ),
        expected_status=201,
    )
    assert moderate["triggered_permanent_deferral"] is False
    assert _instant(moderate["reported_at"]) == _instant("2026-08-15T09:30:00Z")

    after_moderate = validate_success(api.get_donor(donor["id"], liaison))
    assert after_moderate["adverse_event_count"] == 1
    assert _instant(after_moderate["last_followup_at"]) == _instant("2026-08-15T09:30:00Z")
    assert after_moderate["availability_status"] == "AVAILABLE", (
        "a grade-3 event is below the permanent-deferral threshold"
    )

    fixtures.set_clock("2026-09-01T12:00:00Z")
    serious = validate_success(
        api.create_follow_up(
            donor["id"],
            f.create_follow_up_payload("ADVERSE_EVENT", 4),
            physician_headers,
        ),
        expected_status=201,
    )
    assert serious["triggered_permanent_deferral"] is True
    assert _instant(serious["reported_at"]) == _instant("2026-09-01T12:00:00Z")

    after_serious = validate_success(api.get_donor(donor["id"], liaison))
    assert after_serious["adverse_event_count"] == 2
    assert _instant(after_serious["last_followup_at"]) == _instant("2026-09-01T12:00:00Z")
    assert after_serious["availability_status"] == "PERMANENTLY_DEFERRED"

    rows, meta = validate_paginated(api.list_follow_ups(donor["id"], liaison))
    assert meta["total_count"] == 3
    assert [row["event_type"] for row in rows] == [
        "DAY_7_CONTACT",
        "ADVERSE_EVENT",
        "ADVERSE_EVENT",
    ], "follow-up rows list in created_at ascending order"
    assert [row["severity_grade"] for row in rows] == [0, 3, 4]
    assert [row["triggered_permanent_deferral"] for row in rows] == [False, False, True]
