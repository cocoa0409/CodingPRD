"""Boundary precision: the exact point at which a threshold flips the answer.

Two thresholds are probed from both sides.  The preliminary-score floor of a
registry search is an inclusive two-decimal comparison, so one hundredth of a
point separates a materialised candidate pool from an empty, terminal search.
The confirmatory-typing deadline is a UTC instant compared strictly, so a sweep
landing exactly on the deadline expires nothing while a sweep one second later
expires the very same request.
"""
from datetime import datetime

from test_helpers import (
    factories as f,
    fixtures,
    validate_paginated,
    validate_success,
)

DONOR_EXACT_PRELIMINARY_SCORE = 94.75
FLOOR_ONE_HUNDREDTH_ABOVE = 94.76

DOMESTIC_DEADLINE_AT = "2026-08-08T00:00:00Z"
INTERNATIONAL_DEADLINE_AT = "2026-08-10T00:00:00Z"
PRIORITY_DEADLINE_AT = "2026-08-07T00:00:00Z"
SWEEP_ON_DEADLINE_AT = "2026-08-08T00:00:00Z"
SWEEP_ONE_SECOND_LATER_AT = "2026-08-08T00:00:01Z"

INTERNATIONAL_DONOR_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "11:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06", "02"],
}

THIRD_DONOR_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "15:01"],
    "C": ["07:02", "03:04"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06:02", "02:01"],
}


def _instant(value: str) -> datetime:
    """One UTC instant, parsed so that any legal ISO 8601 rendering compares equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_scored_donor_and_patient():
    """One domestic registry, one donor scoring exactly 94.75, one patient."""
    ctx = fixtures.setup_programme(with_center=False)
    fixtures.add_donor(ctx)
    patient = fixtures.create_patient()
    ctx["patient"] = patient
    ctx["patient_id"] = patient["id"]
    return ctx


def _setup_three_typing_requests():
    """Three candidates of one search, each carrying a differently derived deadline.

    All three requests are raised at the clock's mandated default instant
    2026-08-01T00:00:00Z against registries contracted for 168 hours, so the
    domestic request falls due at 2026-08-08T00:00:00Z, the international one
    picks up 48 further hours of grace, and the urgent domestic one loses 24.
    """
    ctx = fixtures.setup_programme(with_center=False)
    international = fixtures.create_international_registry(ct_response_deadline_hours=168)
    ctx["international_registry"] = international

    domestic_donor = fixtures.add_donor(ctx, age_years=27)
    international_donor = fixtures.add_donor(
        ctx,
        registry_id=international["id"],
        donor_code=f"D-{f.unique_suffix()}",
        age_years=41,
        sex="M",
        weight_kg=84.0,
        cmv_status="NEGATIVE",
        hla_typing_registry=dict(INTERNATIONAL_DONOR_HLA),
        ambiguous_loci=["DQB1"],
        prior_donation_count=1,
    )
    urgent_donor = fixtures.add_donor(
        ctx,
        age_years=55,
        sex="M",
        weight_kg=91.0,
        hla_typing_registry=dict(THIRD_DONOR_HLA),
        ambiguous_loci=[],
        consented_methods=["PBSC"],
    )

    patient = fixtures.create_patient()
    ctx["patient"] = patient
    ctx["patient_id"] = patient["id"]
    search = fixtures.open_search(patient["id"], search_scope="DOMESTIC_AND_INTERNATIONAL")
    ctx["search"] = search
    ctx["search_id"] = search["id"]

    candidates = fixtures.list_candidates(search["id"])
    by_donor = {candidate["donor_id"]: candidate for candidate in candidates}
    assert len(by_donor) == 3, (
        f"Setup failed: expected all three donors materialised, got {len(by_donor)}"
    )
    ctx["candidates"] = candidates
    ctx["candidate"] = by_donor[domestic_donor["id"]]
    ctx["candidate_id"] = by_donor[domestic_donor["id"]]["id"]

    requests = {
        "domestic": fixtures.advance_to_typing_requested(
            ctx, by_donor[domestic_donor["id"]]["id"], priority_flag=False
        ),
        "international": fixtures.advance_to_typing_requested(
            ctx, by_donor[international_donor["id"]]["id"], priority_flag=False
        ),
        "urgent": fixtures.advance_to_typing_requested(
            ctx, by_donor[urgent_donor["id"]]["id"], priority_flag=True
        ),
    }
    return ctx, {
        "domestic": by_donor[domestic_donor["id"]],
        "international": by_donor[international_donor["id"]],
        "urgent": by_donor[urgent_donor["id"]],
    }, requests


def _read_typing_request(api, candidate_id, request_id, headers):
    """One of a candidate's typing requests, re-read through its candidate."""
    rows, _ = validate_paginated(api.list_typing_requests(candidate_id, headers))
    for row in rows:
        if row["id"] == request_id:
            return row
    raise AssertionError(
        f"typing request {request_id} is not listed under candidate {candidate_id}: {rows!r}"
    )


def test_donor_scoring_exactly_the_floor_is_admitted_to_the_pool(api):
    """PRD §3.3: "The donor's preliminary match score must be greater than or equal to the search's `min_preliminary_score` — a donor whose score exactly equals the floor is admitted."
    PRD §3.3: "The weighted sum accumulates, locus by locus, the locus weight multiplied by that locus's matched count, using weights of 1.0 for `A`, 1.0 for `B`, 0.8 for `C`, 1.4 for `DRB1` and 0.6 for `DQB1`."
    PRD §3.3: "The base score is one hundred multiplied by the weighted sum and divided by 9.6, where 9.6 is the weighted sum a perfect ten-of-ten match would produce, namely twice the sum of the five weights."
    PRD §3.3: "The raw score is the base minus the penalty plus the bonus; the stored value is that raw score rounded half up to two decimal places and then clamped into the closed range 0.00 to 100.00."
    PRD §3.3: "Roles follow directly from position: the candidate at position 1 becomes `PRIMARY`, positions 2 and 3 become `BACKUP` — two backup slots — and positions 4 and 5 become `ARCHIVED_POOL`."
    PRD §2.10: "`SearchRequest.match_pool_size` is the count of match candidates belonging to that search."

    Design: Difficulty/boundary_precision_check/preliminary_score_floor_is_inclusive_to_the_hundredth
    """
    ctx = _setup_scored_donor_and_patient()

    # The floor is set to the donor's own score to the hundredth: 94.75.
    response = api.create_search_request(
        f.create_search_request_payload(
            ctx["patient_id"], min_preliminary_score=DONOR_EXACT_PRELIMINARY_SCORE
        ),
        ctx["coordinator_headers"],
    )
    search = validate_success(response, expected_status=201)

    assert search["min_preliminary_score"] == DONOR_EXACT_PRELIMINARY_SCORE, (
        "the supplied floor must be stored as given, got "
        f"{search['min_preliminary_score']}"
    )
    assert search["status"] == "SEARCHING", (
        f"a search with a materialised pool opens in SEARCHING, got {search['status']}"
    )
    assert search["match_pool_size"] == 1, (
        "the donor sitting exactly on the floor must be materialised, so "
        f"match_pool_size is 1, got {search['match_pool_size']}"
    )

    candidates, meta = validate_paginated(
        api.list_match_candidates(
            ctx["coordinator_headers"], params={"search_request_id": search["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one candidate row must exist, got {meta['total_count']}"
    )
    candidate = candidates[0]
    assert candidate["preliminary_score"] == DONOR_EXACT_PRELIMINARY_SCORE, (
        "the admitted donor's stored preliminary score must be exactly the floor, got "
        f"{candidate['preliminary_score']}"
    )
    assert candidate["rank_position"] == 1, (
        f"the only survivor takes rank_position 1, got {candidate['rank_position']}"
    )
    assert candidate["candidate_role"] == "PRIMARY", (
        f"position 1 becomes PRIMARY, got {candidate['candidate_role']}"
    )
    assert candidate["status"] == "IDENTIFIED", (
        f"a freshly materialised candidate opens in IDENTIFIED, got {candidate['status']}"
    )


def test_floor_one_hundredth_above_the_donor_score_empties_the_pool(api):
    """PRD §3.3: "The donor's preliminary match score must be greater than or equal to the search's `min_preliminary_score` — a donor whose score exactly equals the floor is admitted."
    PRD §3.3: "If not a single donor survives eligibility, the search moves to `NO_MATCH_FOUND` inside the creation call itself and writes no candidate rows at all: `match_pool_size` stays at zero, and the row is never observable in `SEARCHING`."
    PRD §2.10: "`SearchRequest.backup_candidate_count` is the count of that search's candidates whose `candidate_role` is `BACKUP` and whose `status` is one of `IDENTIFIED`, `TYPING_REQUESTED`, `TYPING_RESPONDED` or `SCREENING_PASSED`."

    Design: Difficulty/boundary_precision_check/preliminary_score_floor_is_inclusive_to_the_hundredth
    """
    ctx = _setup_scored_donor_and_patient()

    # One hundredth of a point higher than the same donor's 94.75, which is the
    # smallest step the two-decimal comparison can register.
    response = api.create_search_request(
        f.create_search_request_payload(
            ctx["patient_id"], min_preliminary_score=FLOOR_ONE_HUNDREDTH_ABOVE
        ),
        ctx["coordinator_headers"],
    )
    search = validate_success(response, expected_status=201)

    assert search["min_preliminary_score"] == FLOOR_ONE_HUNDREDTH_ABOVE, (
        f"the supplied floor must be stored as given, got {search['min_preliminary_score']}"
    )
    assert search["status"] == "NO_MATCH_FOUND", (
        "with no donor reaching the floor the creation call itself must land in "
        f"NO_MATCH_FOUND, got {search['status']}"
    )
    assert search["match_pool_size"] == 0, (
        f"no candidate rows are written, so match_pool_size stays 0, got {search['match_pool_size']}"
    )
    assert search["backup_candidate_count"] == 0, (
        f"an empty pool holds no backups, got {search['backup_candidate_count']}"
    )
    assert search["last_sweep_at"] is None, (
        f"a new search starts with last_sweep_at null, got {search['last_sweep_at']}"
    )

    candidates, meta = validate_paginated(
        api.list_match_candidates(
            ctx["coordinator_headers"], params={"search_request_id": search["id"]}
        )
    )
    assert candidates == [] and meta["total_count"] == 0, (
        f"the terminal search must expose no candidate rows, got {meta['total_count']}"
    )


def test_sweep_landing_exactly_on_the_deadline_expires_nothing(api):
    """PRD §3.4: "For each of them, the current logical instant is compared against `deadline_at` with a strict test: only a request whose deadline lies strictly before the current instant expires."
    PRD §3.4: "A sweep that lands at exactly the deadline instant expires nothing; a sweep one second later expires it."
    PRD §3.4: "It begins at `requested_at` plus the donor registry's contractual `ct_response_deadline_hours`."
    PRD §3.4: "When the donor's registry has `is_domestic` false, a further 48 hours of grace — two full days — are added, in recognition of the time zones and translation involved in international coordination."
    PRD §3.4: "When `priority_flag` is true, 24 hours are subtracted."
    PRD §3.4: "An expiring request moves `REQUESTED → EXPIRED`, has `expired_by_sweep_at` stamped with the sweep instant, and drags its candidate `TYPING_REQUESTED → TYPING_EXPIRED`."
    PRD §3.4: "Every sweep stamps the search's `last_sweep_at` with the sweep instant, whether or not anything expired."

    Design: Difficulty/boundary_precision_check/typing_deadline_expiry_is_strictly_after_the_deadline_instant
    """
    ctx, candidates, requests = _setup_three_typing_requests()

    assert _instant(requests["domestic"]["deadline_at"]) == _instant(DOMESTIC_DEADLINE_AT), (
        "Setup failed: 168 contractual hours from 2026-08-01T00:00:00Z fall due at "
        f"{DOMESTIC_DEADLINE_AT}, got {requests['domestic']['deadline_at']}"
    )
    assert _instant(requests["international"]["deadline_at"]) == _instant(
        INTERNATIONAL_DEADLINE_AT
    ), (
        "Setup failed: 168 hours plus 48 hours of international grace fall due at "
        f"{INTERNATIONAL_DEADLINE_AT}, got {requests['international']['deadline_at']}"
    )
    assert _instant(requests["urgent"]["deadline_at"]) == _instant(PRIORITY_DEADLINE_AT), (
        "Setup failed: 168 hours less the 24-hour urgency subtraction fall due at "
        f"{PRIORITY_DEADLINE_AT}, got {requests['urgent']['deadline_at']}"
    )

    # The sweep instant is the domestic request's own deadline, to the second.
    fixtures.set_clock(SWEEP_ON_DEADLINE_AT)
    search = fixtures.sweep(ctx)

    on_boundary = _read_typing_request(
        api,
        candidates["domestic"]["id"],
        requests["domestic"]["id"],
        ctx["coordinator_headers"],
    )
    assert on_boundary["status"] == "REQUESTED", (
        "a request whose deadline equals the sweep instant does not lie strictly "
        f"before it and must survive, got {on_boundary['status']}"
    )
    assert on_boundary["expired_by_sweep_at"] is None, (
        f"a surviving request is stamped by no sweep, got {on_boundary['expired_by_sweep_at']}"
    )
    assert fixtures.read_candidate(candidates["domestic"]["id"])["status"] == "TYPING_REQUESTED", (
        "the surviving request's candidate is untouched"
    )

    later = _read_typing_request(
        api,
        candidates["international"]["id"],
        requests["international"]["id"],
        ctx["coordinator_headers"],
    )
    assert later["status"] == "REQUESTED", (
        f"a deadline two days out is far from due, got {later['status']}"
    )

    already_due = _read_typing_request(
        api,
        candidates["urgent"]["id"],
        requests["urgent"]["id"],
        ctx["coordinator_headers"],
    )
    assert already_due["status"] == "EXPIRED", (
        "the urgent request's deadline lies strictly before the sweep instant, so it "
        f"must expire, got {already_due['status']}"
    )
    assert _instant(already_due["expired_by_sweep_at"]) == _instant(SWEEP_ON_DEADLINE_AT), (
        "the expiring request carries the sweep instant, got "
        f"{already_due['expired_by_sweep_at']}"
    )
    urgent_candidate = fixtures.read_candidate(candidates["urgent"]["id"])
    assert urgent_candidate["status"] == "TYPING_EXPIRED", (
        f"the expiring request drags its candidate along, got {urgent_candidate['status']}"
    )
    assert urgent_candidate["ct_attempt_count"] == 1, (
        "expiry consumes no further attempt, got "
        f"{urgent_candidate['ct_attempt_count']}"
    )

    assert _instant(search["last_sweep_at"]) == _instant(SWEEP_ON_DEADLINE_AT), (
        f"every sweep stamps last_sweep_at, got {search['last_sweep_at']}"
    )


def test_sweep_one_second_past_the_deadline_expires_the_request(api):
    """PRD §3.4: "For each of them, the current logical instant is compared against `deadline_at` with a strict test: only a request whose deadline lies strictly before the current instant expires."
    PRD §3.4: "A sweep that lands at exactly the deadline instant expires nothing; a sweep one second later expires it."
    PRD §3.4: "An expiring request moves `REQUESTED → EXPIRED`, has `expired_by_sweep_at` stamped with the sweep instant, and drags its candidate `TYPING_REQUESTED → TYPING_EXPIRED`."
    PRD §3.4: "Every sweep stamps the search's `last_sweep_at` with the sweep instant, whether or not anything expired."
    PRD §3.4: "A `BACKUP` candidate at two attempts is deliberately *not* auto-excluded: it rests in `TYPING_EXPIRED`, which is precisely how a later third request against it becomes reachable and is refused with `ERR_CT_ATTEMPTS_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/typing_deadline_expiry_is_strictly_after_the_deadline_instant
    """
    ctx, candidates, requests = _setup_three_typing_requests()
    assert _instant(requests["domestic"]["deadline_at"]) == _instant(DOMESTIC_DEADLINE_AT), (
        "Setup failed: the domestic deadline must be "
        f"{DOMESTIC_DEADLINE_AT}, got {requests['domestic']['deadline_at']}"
    )

    # One single second past the very instant that expired nothing.
    fixtures.set_clock(SWEEP_ONE_SECOND_LATER_AT)
    search = fixtures.sweep(ctx)

    just_past = _read_typing_request(
        api,
        candidates["domestic"]["id"],
        requests["domestic"]["id"],
        ctx["coordinator_headers"],
    )
    assert just_past["status"] == "EXPIRED", (
        "one second past the deadline the request's deadline lies strictly before "
        f"the sweep instant and it must expire, got {just_past['status']}"
    )
    assert _instant(just_past["expired_by_sweep_at"]) == _instant(SWEEP_ONE_SECOND_LATER_AT), (
        f"expired_by_sweep_at carries the sweep instant, got {just_past['expired_by_sweep_at']}"
    )
    assert just_past["responded_at"] is None, (
        f"an expired request was never answered, got {just_past['responded_at']}"
    )

    domestic_candidate = fixtures.read_candidate(candidates["domestic"]["id"])
    assert domestic_candidate["status"] == "TYPING_EXPIRED", (
        f"the candidate is dragged to TYPING_EXPIRED, got {domestic_candidate['status']}"
    )
    assert domestic_candidate["ct_attempt_count"] == 1, (
        "the first attempt is spent and no more, got "
        f"{domestic_candidate['ct_attempt_count']}"
    )
    assert domestic_candidate["candidate_role"] == "PRIMARY", (
        "a primary with attempts left is not excluded and keeps its role, got "
        f"{domestic_candidate['candidate_role']}"
    )

    still_open = _read_typing_request(
        api,
        candidates["international"]["id"],
        requests["international"]["id"],
        ctx["coordinator_headers"],
    )
    assert still_open["status"] == "REQUESTED", (
        "the international deadline is two days further out and is untouched by the "
        f"same sweep, got {still_open['status']}"
    )
    assert still_open["expired_by_sweep_at"] is None, (
        f"an untouched request bears no sweep stamp, got {still_open['expired_by_sweep_at']}"
    )

    assert _instant(search["last_sweep_at"]) == _instant(SWEEP_ONE_SECOND_LATER_AT), (
        f"every sweep stamps last_sweep_at, got {search['last_sweep_at']}"
    )
