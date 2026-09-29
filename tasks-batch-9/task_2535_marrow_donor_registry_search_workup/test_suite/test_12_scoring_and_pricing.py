"""Scoring, ranking, deadline arithmetic and the repeatable expiry sweep.

Every test in this file builds its own registries, donor pool, patient and
search from scratch: the logical clock starts at 2026-08-01T00:00:00Z against an
empty database, so a score, a deadline instant and a sweep instant are all
exactly reproducible.
"""
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    assertions as A,
    constants as C,
    factories as f,
    fixtures,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
OPERATIONS = TEST_USERS["operations_headers"]


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, whatever fractional precision it carries.

    Instant-valued fields are compared exactly to the second, so the tests
    compare parsed instants rather than rendered strings.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


CLOCK_EPOCH = C.CLOCK_EPOCH  # 2026-08-01T00:00:00Z

# --- the donor archetypes the score arithmetic is pinned on -------------------
# D1 is the factory default donor: locus C antigen-level, ambiguous_loci ["C"].
D2_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "11:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06", "02"],
}
D3_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "15:01"],
    "C": ["07:02", "03:04"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06:02", "02:01"],
}
D5_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "15:01"],
    "C": ["07:02", "03:04"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06:02", "05:01"],
}

DONOR_D1 = {"donor_code": "D-0001"}
DONOR_D2 = {
    "donor_code": "D-0002",
    "age_years": 41,
    "sex": "M",
    "weight_kg": 84.0,
    "cmv_status": "NEGATIVE",
    "hla_typing_registry": D2_HLA,
    "consented_methods": ["PBSC", "MARROW"],
    "ambiguous_loci": ["DQB1"],
    "prior_donation_count": 1,
}
DONOR_D3 = {
    "donor_code": "D-0003",
    "age_years": 55,
    "sex": "M",
    "weight_kg": 91.0,
    "cmv_status": "POSITIVE",
    "hla_typing_registry": D3_HLA,
    "consented_methods": ["PBSC"],
    "ambiguous_loci": [],
    "prior_donation_count": 0,
}
DONOR_D5 = {
    "donor_code": "D-0005",
    "age_years": 30,
    "sex": "F",
    "weight_kg": 72.0,
    "cmv_status": "POSITIVE",
    "hla_typing_registry": D5_HLA,
    "consented_methods": ["PBSC", "MARROW"],
    "ambiguous_loci": [],
    "prior_donation_count": 0,
}
DONOR_D6 = {
    "donor_code": "D-0006",
    "age_years": 65,
    "sex": "M",
    "weight_kg": 80.0,
    "cmv_status": "POSITIVE",
    "hla_typing_registry": f.DONOR_HLA_FULL_ALLELE,
    "consented_methods": ["PBSC"],
    "ambiguous_loci": [],
    "prior_donation_count": 0,
}
DONOR_D7 = {
    "donor_code": "D-0007",
    "age_years": 24,
    "sex": "F",
    "weight_kg": 61.0,
    "cmv_status": "POSITIVE",
    "hla_typing_registry": f.DONOR_HLA_FULL_ALLELE,
    "consented_methods": ["PBSC"],
    "ambiguous_loci": [],
    "availability_status": "WITHDRAWN",
    "prior_donation_count": 0,
}
DONOR_D8 = {"donor_code": "D-0008"}


def _open_search(api, patient_id, **overrides):
    """Open a search and validate the 201 create envelope."""
    payload = f.create_search_request_payload(patient_id, **overrides)
    return validate_success(api.create_search_request(payload, COORDINATOR), 201)


def _candidates(api, search_id):
    """The search's candidates, in the list ordering the PRD pins."""
    return validate_paginated(
        api.list_match_candidates(
            COORDINATOR, params={"search_request_id": search_id, "limit": 100}
        )
    )


def test_pool_is_ordered_and_role_assigned_by_rank_score(api):
    """PRD §3.3: "Eligible donors are ordered by `rank_score` descending, then — for donors whose ranking scores tie — by `preliminary_score` descending, and finally by the donor profile's `created_at` ascending, so that the volunteer enrolled earliest wins a genuine tie."
    PRD §3.3: "The first five rows of that ordering are materialised as match candidates and everything beyond the fifth is discarded; the survivors receive `rank_position` values 1 through however many were kept."
    PRD §3.3: "Roles follow directly from position: the candidate at position 1 becomes `PRIMARY`, positions 2 and 3 become `BACKUP` — two backup slots — and positions 4 and 5 become `ARCHIVED_POOL`."
    PRD §3.3: "Each materialised candidate records its `search_request_id`, its `donor_id`, the computed `preliminary_score` and `rank_score`, its frozen `rank_position` and its `candidate_role`, opens in `status` `IDENTIFIED` with `ct_attempt_count` at zero, and carries `confirmed_score`, `confirmed_match_grade`, `screening_outcome`, `screening_deferral_type` and `promoted_from_rank` all null."
    PRD §3.3: "The search's `match_pool_size` records how many candidates were written and `backup_candidate_count` records how many of them are backups."
    PRD §3.3: "The coordinator supplies `patient_id`, a `search_scope` of either `DOMESTIC_ONLY` or `DOMESTIC_AND_INTERNATIONAL`, and optionally `min_preliminary_score` — a two-decimal number in the closed range 0.00 to 100.00 that defaults to 60.00 and acts as the floor a donor must reach to be worth materialising."
    PRD §3.3: "The seven legal search states are `SEARCHING`, `NO_MATCH_FOUND`, `PRIMARY_ENGAGED`, `WORKUP_ACTIVE`, `BACKUP_REQUIRED`, `STALLED` and `FULFILLED`; a new search starts in `SEARCHING` with `last_sweep_at` null, and `NO_MATCH_FOUND` and `FULFILLED` are terminal."
    PRD §3.3: "The raw score is the base minus the penalty plus the bonus; the stored value is that raw score rounded half up to two decimal places and then clamped into the closed range 0.00 to 100.00."
    PRD §3.3: "The ranking score is then 0.55 multiplied by the donor's already-rounded two-decimal `preliminary_score`, plus 0.25 multiplied by the age factor, plus 0.20 multiplied by the logistics factor, with the resulting weighted sum rounded half up to three decimal places exactly once."

    Design: Corner/calculations/the_materialized_pool_is_ordered_and_role_assigned_by_rank_score
    """
    ctx = fixtures.setup_programme(with_center=False)
    intl = fixtures.create_international_registry(ct_response_deadline_hours=120)

    d1 = fixtures.add_donor(ctx, **DONOR_D1)
    d2 = fixtures.add_donor(ctx, registry_id=intl["id"], **DONOR_D2)
    d3 = fixtures.add_donor(ctx, **DONOR_D3)
    d5 = fixtures.add_donor(ctx, **DONOR_D5)

    patient = fixtures.create_patient()
    search = _open_search(api, patient["id"], search_scope="DOMESTIC_AND_INTERNATIONAL")

    assert search["status"] == "SEARCHING", (
        f"a new search opens in SEARCHING, got {search['status']!r}"
    )
    assert float(search["min_preliminary_score"]) == pytest.approx(60.00, abs=0.001), (
        "an omitted min_preliminary_score defaults to 60.00, got "
        f"{search['min_preliminary_score']!r}"
    )
    assert search["match_pool_size"] == 4, (
        f"four eligible donors were materialised, got match_pool_size "
        f"{search['match_pool_size']}"
    )
    assert search["backup_candidate_count"] == 2, (
        "only the two BACKUP rows count towards backup_candidate_count, got "
        f"{search['backup_candidate_count']}"
    )

    candidates, meta = _candidates(api, search["id"])
    assert meta["total_count"] == 4, f"expected four candidate rows, got {meta}"

    # rank_score DESC: D1 97.113, D5 78.831, D2 76.869, D3 65.544 — D5 outranks D2
    # even though D2's preliminary_score 86.58 beats D5's 64.92, because an
    # international donor's logistics factor is capped far below a domestic one's.
    expected = [
        (d1["id"], 94.75, 97.113, 1, "PRIMARY"),
        (d5["id"], 64.92, 78.831, 2, "BACKUP"),
        (d2["id"], 86.58, 76.869, 3, "BACKUP"),
        (d3["id"], 69.17, 65.544, 4, "ARCHIVED_POOL"),
    ]
    assert [c["donor_id"] for c in candidates] == [row[0] for row in expected], (
        "the materialised pool must be ordered by rank_score descending"
    )
    for candidate, (donor_id, prelim, rank, position, role) in zip(candidates, expected):
        A.assert_match_candidate(candidate)
        assert candidate["search_request_id"] == search["id"]
        assert float(candidate["preliminary_score"]) == pytest.approx(prelim, abs=0.001), (
            f"donor {donor_id} preliminary_score expected {prelim}, got "
            f"{candidate['preliminary_score']}"
        )
        assert float(candidate["rank_score"]) == pytest.approx(rank, abs=0.0005), (
            f"donor {donor_id} rank_score expected {rank}, got {candidate['rank_score']}"
        )
        assert candidate["rank_position"] == position, (
            f"donor {donor_id} expected rank_position {position}, got "
            f"{candidate['rank_position']}"
        )
        assert candidate["candidate_role"] == role, (
            f"rank_position {position} must carry candidate_role {role}, got "
            f"{candidate['candidate_role']}"
        )
        assert candidate["status"] == "IDENTIFIED"
        assert candidate["ct_attempt_count"] == 0
        for field in (
            "confirmed_score",
            "confirmed_match_grade",
            "screening_outcome",
            "screening_deferral_type",
            "promoted_from_rank",
        ):
            assert candidate[field] is None, (
                f"a freshly materialised candidate carries {field} null, got "
                f"{candidate[field]!r}"
            )


def test_only_eligible_donors_enter_the_pool(api):
    """PRD §3.3: "Every donor profile in the system, joined to its home registry, is tested against six conditions, and only a donor satisfying all six enters the pool."
    PRD §3.3: "The donor's `availability_status` must be `AVAILABLE`."
    PRD §3.3: "The donor's registry must have `cooperation_status` equal to `ACTIVE`."
    PRD §3.3: "The donor's `age_years` must be at least 18 and at most 60."
    PRD §3.3: "When `search_scope` is `DOMESTIC_ONLY`, the donor's registry must be the domestic one; when it is `DOMESTIC_AND_INTERNATIONAL`, registries of either kind qualify."
    PRD §3.3: "The donor's preliminary match score must be greater than or equal to the search's `min_preliminary_score` — a donor whose score exactly equals the floor is admitted."
    PRD §3.2: "Registration accepts ages from 17 through 75 inclusive — registries do enrol volunteers slightly outside the collection age band, and rejecting them at enrolment would corrupt the registry's own records — but the search eligibility filter of §3.3 admits only volunteers aged 18 through 60 inclusive, so a 17-year-old or a 61-year-old is a perfectly valid profile that will never be materialised into a candidate."
    PRD §3.1: "An operations update may adjust `cooperation_status`, `cooperation_tier`, `fx_rate_to_usd` or `ct_response_deadline_hours`, each optionally, and each such update increments the registry's `version` by one."
    PRD §3.3: "The search's `match_pool_size` records how many candidates were written and `backup_candidate_count` records how many of them are backups."

    Design: Corner/calculations/only_eligible_donors_enter_the_materialized_pool
    """
    ctx = fixtures.setup_programme(with_center=False)
    suspended = fixtures.create_registry(name="Regional Marrow Program", cooperation_tier=3)
    intl = fixtures.create_international_registry()

    d1 = fixtures.add_donor(ctx, **DONOR_D1)
    d2 = fixtures.add_donor(ctx, registry_id=intl["id"], **DONOR_D2)
    d3 = fixtures.add_donor(ctx, **DONOR_D3)
    d5 = fixtures.add_donor(ctx, **DONOR_D5)
    d6 = fixtures.add_donor(ctx, **DONOR_D6)
    d7 = fixtures.add_donor(ctx, **DONOR_D7)
    # D8 is a typing twin of D1 and would tie at 94.75 if the cooperation clause
    # were skipped, so its registry is suspended only after it is on file.
    d8 = fixtures.add_donor(ctx, registry_id=suspended["id"], **DONOR_D8)

    suspended = validate_success(
        api.update_registry(suspended["id"], {"cooperation_status": "SUSPENDED"}, OPERATIONS)
    )
    assert suspended["cooperation_status"] == "SUSPENDED", (
        f"the second domestic registry must be SUSPENDED, got {suspended!r}"
    )

    patient = fixtures.create_patient()
    search = _open_search(
        api, patient["id"], search_scope="DOMESTIC_ONLY", min_preliminary_score=70.00
    )

    assert search["status"] == "SEARCHING", (
        f"a non-empty pool never yields NO_MATCH_FOUND, got {search['status']!r}"
    )
    assert search["match_pool_size"] == 1, (
        "only D1 satisfies all six eligibility conditions, got match_pool_size "
        f"{search['match_pool_size']}"
    )
    assert search["backup_candidate_count"] == 0, (
        f"a one-donor pool has no backups, got {search['backup_candidate_count']}"
    )

    candidates, meta = _candidates(api, search["id"])
    assert meta["total_count"] == 1, (
        f"exactly one candidate row may exist, got total_count {meta['total_count']}"
    )
    assert len(candidates) == 1, f"expected one candidate row, got {candidates!r}"

    only = candidates[0]
    assert only["donor_id"] == d1["id"], (
        f"the sole candidate must be D1 ({d1['id']}), got {only['donor_id']}"
    )
    assert float(only["preliminary_score"]) == pytest.approx(94.75, abs=0.001), (
        f"D1's preliminary_score is 94.75, got {only['preliminary_score']}"
    )
    assert only["rank_position"] == 1, (
        f"the survivor takes rank_position 1, got {only['rank_position']}"
    )
    assert only["candidate_role"] == "PRIMARY", (
        f"position 1 becomes PRIMARY, got {only['candidate_role']}"
    )

    materialised = {candidate["donor_id"] for candidate in candidates}
    for label, donor, reason in (
        ("D2", d2, "search_scope DOMESTIC_ONLY excludes an international registry"),
        ("D3", d3, "preliminary_score 69.17 misses the 70.00 floor by 0.83"),
        ("D5", d5, "preliminary_score 64.92 is below the 70.00 floor"),
        ("D6", d6, "age 65 is outside the 18-to-60 eligibility band"),
        ("D7", d7, "availability_status is WITHDRAWN, not AVAILABLE"),
        ("D8", d8, "its home registry's cooperation_status is SUSPENDED"),
    ):
        assert donor["id"] not in materialised, (
            f"{label} must not be materialised: {reason}"
        )


def test_typing_deadlines_apply_the_grace_and_priority_constants(api):
    """PRD §3.4: "The deadline is computed once, at request time, and then frozen."
    PRD §3.4: "It begins at `requested_at` plus the donor registry's contractual `ct_response_deadline_hours`."
    PRD §3.4: "When the donor's registry has `is_domestic` false, a further 48 hours of grace — two full days — are added, in recognition of the time zones and translation involved in international coordination."
    PRD §3.4: "When `priority_flag` is true, 24 hours are subtracted."
    PRD §3.4: "All three adjustments are whole hours applied to the stored instant, and they combine: an urgent request against a partner registry gets the contractual hours plus 48 minus 24, a net addition of 24 hours."
    PRD §3.4: "The created request records `match_candidate_id`, an `attempt_number` equal to the candidate's `ct_attempt_count` after the increment — so 1 or 2 — a `requested_at` stamped from the logical clock, and a computed `deadline_at`."
    PRD §3.4: "It opens in `status` `REQUESTED` with `responded_at`, `reported_hla_typing`, `reported_match_grade`, `donor_available_flag` and `expired_by_sweep_at` all null, and its four legal states are `REQUESTED`, `RESPONDED`, `EXPIRED` and `CANCELLED`, the last three all terminal."
    PRD §3.4: "When the candidate carrying the request is the search's `PRIMARY`, the search itself advances `SEARCHING → PRIMARY_ENGAGED`; when the candidate is a newly promoted primary, the same act moves the search `BACKUP_REQUIRED → PRIMARY_ENGAGED`, and that cycle may repeat once for each available backup."
    PRD §3.4: "A successful request raises the candidate's `ct_attempt_count` by one and moves the candidate `IDENTIFIED → TYPING_REQUESTED`, or `TYPING_EXPIRED → TYPING_REQUESTED` on the second attempt, which is exactly why the candidate's history is cyclic: `TYPING_REQUESTED → TYPING_EXPIRED → TYPING_REQUESTED`, bounded to two attempts in total."

    Design: Corner/calculations/typing_deadlines_apply_the_grace_and_priority_constants
    """
    ctx = fixtures.setup_programme(
        with_center=False, registry_overrides={"ct_response_deadline_hours": 168}
    )
    intl = fixtures.create_international_registry(ct_response_deadline_hours=120)

    d1 = fixtures.add_donor(ctx, **DONOR_D1)
    d5 = fixtures.add_donor(ctx, **DONOR_D5)
    d2 = fixtures.add_donor(ctx, registry_id=intl["id"], **DONOR_D2)

    patient = fixtures.create_patient()
    search = _open_search(api, patient["id"], search_scope="DOMESTIC_AND_INTERNATIONAL")
    candidates, _ = _candidates(api, search["id"])
    by_donor = {candidate["donor_id"]: candidate for candidate in candidates}
    assert set(by_donor) == {d1["id"], d5["id"], d2["id"]}, (
        f"all three donors are eligible under DOMESTIC_AND_INTERNATIONAL, got {by_donor.keys()}"
    )
    assert by_donor[d1["id"]]["candidate_role"] == "PRIMARY"
    assert by_donor[d5["id"]]["candidate_role"] == "BACKUP"
    assert by_donor[d2["id"]]["candidate_role"] == "BACKUP"

    requested_at = _utc(CLOCK_EPOCH)
    # 168 h contractual, 168 - 24 h priority, 120 + 48 h grace: the domestic and
    # the international non-priority deadlines coincide, so a wrong grace value
    # cannot hide behind the coincidence.
    cases = [
        (d1["id"], False, 168, "domestic, no grace, no reduction"),
        (d5["id"], True, 144, "domestic minus the 24 h priority reduction"),
        (d2["id"], False, 168, "120 contractual plus the 48 h international grace"),
    ]
    for donor_id, priority, hours, why in cases:
        candidate_id = by_donor[donor_id]["id"]
        created = validate_success(
            api.create_typing_request(
                candidate_id,
                f.create_typing_request_payload(priority_flag=priority),
                COORDINATOR,
            ),
            201,
        )
        A.assert_typing_request(created)
        assert created["match_candidate_id"] == candidate_id
        assert created["priority_flag"] is priority
        assert created["attempt_number"] == 1, (
            f"a first request carries attempt_number 1, got {created['attempt_number']}"
        )
        assert created["status"] == "REQUESTED"
        for field in (
            "responded_at",
            "reported_hla_typing",
            "reported_match_grade",
            "donor_available_flag",
            "expired_by_sweep_at",
        ):
            assert created[field] is None, (
                f"a fresh typing request carries {field} null, got {created[field]!r}"
            )
        assert _instant(created["requested_at"]) == requested_at, (
            f"requested_at is stamped from the logical clock {CLOCK_EPOCH}, got "
            f"{created['requested_at']}"
        )
        assert _instant(created["deadline_at"]) == requested_at + timedelta(hours=hours), (
            f"deadline_at must be requested_at plus {hours} hours ({why}), got "
            f"{created['deadline_at']}"
        )

        candidate = validate_success(api.get_match_candidate(candidate_id, COORDINATOR))
        assert candidate["status"] == "TYPING_REQUESTED", (
            f"a successful request moves the candidate to TYPING_REQUESTED, got "
            f"{candidate['status']}"
        )
        assert candidate["ct_attempt_count"] == 1, (
            f"a successful request raises ct_attempt_count to 1, got "
            f"{candidate['ct_attempt_count']}"
        )

    reread = validate_success(api.get_search_request(search["id"], COORDINATOR))
    assert reread["status"] == "PRIMARY_ENGAGED", (
        "only the request on the PRIMARY candidate moves the search, and it moves it "
        f"to PRIMARY_ENGAGED, got {reread['status']}"
    )


def test_scores_are_rounded_half_up_exactly_once(api):
    """PRD §3.3: "The raw score is the base minus the penalty plus the bonus; the stored value is that raw score rounded half up to two decimal places and then clamped into the closed range 0.00 to 100.00."
    PRD §3.3: "There is exactly one rounding step, applied to the raw value at the very end — the base, the penalty and the bonus are all kept exact until then."
    PRD §3.3: "The ranking score is then 0.55 multiplied by the donor's already-rounded two-decimal `preliminary_score`, plus 0.25 multiplied by the age factor, plus 0.20 multiplied by the logistics factor, with the resulting weighted sum rounded half up to three decimal places exactly once."
    PRD §2.6: "Match scores are decimal numbers carried to exactly two decimal places, bounded to the closed range 0.00 to 100.00, and rounded half up."
    PRD §2.6: "The rounding is applied exactly once, to the final raw value of the score computation; every intermediate weighted sum is kept exact and is never rounded on the way."
    PRD §2.6: "Candidate ranking scores are carried to exactly three decimal places, likewise rounded half up exactly once at the end of the weighted sum, and likewise bounded to the closed range 0.000 to 100.000."
    PRD §2.6: "When a ranking score consumes a match score, it consumes the already-rounded two-decimal value, not the exact pre-rounding value."

    Design: Corner/calculations/scores_are_rounded_half_up_exactly_once_at_the_end
    """
    ctx = fixtures.setup_programme(with_center=False)
    d1 = fixtures.add_donor(ctx, **DONOR_D1)
    d3 = fixtures.add_donor(ctx, **DONOR_D3)

    patient = fixtures.create_patient()
    search = _open_search(api, patient["id"], search_scope="DOMESTIC_ONLY")
    candidates, meta = _candidates(api, search["id"])
    assert meta["total_count"] == 2, f"both donors are eligible, got {meta}"
    by_donor = {candidate["donor_id"]: candidate for candidate in candidates}

    first = by_donor[d1["id"]]
    A.assert_two_decimal_places(first["preliminary_score"], "D1.preliminary_score")
    A.assert_three_decimal_places(first["rank_score"], "D1.rank_score")
    assert float(first["preliminary_score"]) == pytest.approx(94.75, abs=0.001), (
        f"D1's raw 94.75 needs no rounding, got {first['preliminary_score']}"
    )
    # 0.55*94.75 + 0.25*100 + 0.20*100 = 52.1125 + 25 + 20 = 97.1125, whose
    # half-up third decimal is 97.113; banker's rounding would give 97.112.
    assert float(first["rank_score"]) == pytest.approx(97.113, abs=0.0005), (
        "D1's rank sum 97.1125 rounds half up to 97.113, not to the banker's-rounding "
        f"answer 97.112; got {first['rank_score']}"
    )

    second = by_donor[d3["id"]]
    A.assert_two_decimal_places(second["preliminary_score"], "D3.preliminary_score")
    A.assert_three_decimal_places(second["rank_score"], "D3.rank_score")
    # D3's base is a non-terminating 66.6666..., and the single half-up step at the
    # very end takes 66.6666... + 2.5 = 69.16666... to 69.17.
    assert float(second["preliminary_score"]) == pytest.approx(69.17, abs=0.001), (
        f"D3's raw 69.16666... rounds half up once to 69.17, got "
        f"{second['preliminary_score']}"
    )
    # 0.55*69.17 + 0.25*30 + 0.20*100 = 38.0435 + 7.5 + 20 = 65.5435 -> 65.544 half up.
    assert float(second["rank_score"]) == pytest.approx(65.544, abs=0.0005), (
        "the ranking blend consumes the already-rounded 69.17 and rounds half up once "
        f"to 65.544, got {second['rank_score']}"
    )


def test_sweep_touches_only_requested_rows_and_always_stamps_last_sweep_at(api):
    """PRD §3.4: "A `RegistryOperations` operator sweeps a search, and the sweep walks that search's typing requests that are still in `REQUESTED` status in `created_at` ascending order."
    PRD §3.4: "For each of them, the current logical instant is compared against `deadline_at` with a strict test: only a request whose deadline lies strictly before the current instant expires."
    PRD §3.4: "A sweep that lands at exactly the deadline instant expires nothing; a sweep one second later expires it."
    PRD §3.4: "An expiring request moves `REQUESTED → EXPIRED`, has `expired_by_sweep_at` stamped with the sweep instant, and drags its candidate `TYPING_REQUESTED → TYPING_EXPIRED`."
    PRD §3.4: "If that candidate is the `PRIMARY` and its `ct_attempt_count` has already reached two, the candidate is additionally moved `TYPING_EXPIRED → EXCLUDED` and the promotion cascade runs."
    PRD §3.4: "Every sweep stamps the search's `last_sweep_at` with the sweep instant, whether or not anything expired."
    PRD §3.4: "The deadline is computed once, at request time, and then frozen."
    PRD §3.4: "It begins at `requested_at` plus the donor registry's contractual `ct_response_deadline_hours`."

    Design: Corner/calculations/a_sweep_touches_only_requested_rows_and_always_stamps_last_sweep_at
    """
    ctx = fixtures.setup_programme(
        with_center=False, registry_overrides={"ct_response_deadline_hours": 168}
    )
    d1 = fixtures.add_donor(ctx, **DONOR_D1)
    d5 = fixtures.add_donor(ctx, **DONOR_D5)

    patient = fixtures.create_patient()
    search = _open_search(api, patient["id"], search_scope="DOMESTIC_ONLY")
    candidates, _ = _candidates(api, search["id"])
    by_donor = {candidate["donor_id"]: candidate for candidate in candidates}
    primary_id = by_donor[d1["id"]]["id"]
    backup_id = by_donor[d5["id"]]["id"]

    first_request = validate_success(
        api.create_typing_request(
            primary_id, f.create_typing_request_payload(), COORDINATOR
        ),
        201,
    )
    first_deadline = _instant(first_request["deadline_at"])
    assert first_deadline == _utc(CLOCK_EPOCH) + timedelta(hours=168), (
        f"the primary's deadline is 168 h after the epoch, got {first_request['deadline_at']}"
    )

    # One second after the frozen deadline the strict test fires.
    first_sweep_at = "2026-08-08T00:00:01Z"
    fixtures.set_clock(first_sweep_at)
    swept = validate_success(api.run_deadline_sweep(search["id"], OPERATIONS))
    assert _instant(swept["last_sweep_at"]) == _utc(first_sweep_at), (
        f"last_sweep_at must carry the sweep instant, got {swept['last_sweep_at']}"
    )
    assert swept["status"] == "PRIMARY_ENGAGED", (
        "a first-attempt expiry on the primary runs no cascade, so the search stays "
        f"PRIMARY_ENGAGED, got {swept['status']}"
    )
    assert swept["backup_candidate_count"] == 1, (
        f"no backup was consumed, got backup_candidate_count {swept['backup_candidate_count']}"
    )

    rows, _ = validate_paginated(api.list_typing_requests(primary_id, OPERATIONS))
    assert len(rows) == 1, f"the primary has exactly one typing request, got {rows!r}"
    expired = rows[0]
    assert expired["status"] == "EXPIRED", (
        f"the overdue REQUESTED row expires, got {expired['status']}"
    )
    assert _instant(expired["expired_by_sweep_at"]) == _utc(first_sweep_at), (
        f"expired_by_sweep_at carries the sweep instant, got {expired['expired_by_sweep_at']}"
    )

    primary = validate_success(api.get_match_candidate(primary_id, OPERATIONS))
    assert primary["status"] == "TYPING_EXPIRED", (
        f"the expiring request drags its candidate to TYPING_EXPIRED, got {primary['status']}"
    )
    assert primary["ct_attempt_count"] == 1, (
        f"the expiry consumes no further attempt, got {primary['ct_attempt_count']}"
    )
    assert primary["candidate_role"] == "PRIMARY", (
        "one attempt is below the ceiling of two, so the primary is not auto-excluded and "
        f"keeps its role, got {primary['candidate_role']}"
    )
    assert primary["promoted_from_rank"] is None, (
        f"no promotion ran, got promoted_from_rank {primary['promoted_from_rank']!r}"
    )
    backup = validate_success(api.get_match_candidate(backup_id, OPERATIONS))
    assert backup["candidate_role"] == "BACKUP", (
        f"the backup was not promoted, got {backup['candidate_role']}"
    )

    # A fresh request on the still-BACKUP candidate computes its own frozen deadline.
    second_request = validate_success(
        api.create_typing_request(
            backup_id, f.create_typing_request_payload(), COORDINATOR
        ),
        201,
    )
    assert _instant(second_request["requested_at"]) == _utc(first_sweep_at)
    assert _instant(second_request["deadline_at"]) == _utc(first_sweep_at) + timedelta(hours=168), (
        "the second request's deadline is 168 h from its own requested_at, got "
        f"{second_request['deadline_at']}"
    )

    second_sweep_at = "2026-08-10T00:00:00Z"
    fixtures.set_clock(second_sweep_at)
    swept_again = validate_success(api.run_deadline_sweep(search["id"], OPERATIONS))
    assert _instant(swept_again["last_sweep_at"]) == _utc(second_sweep_at), (
        "a sweep that expires nothing still stamps last_sweep_at, got "
        f"{swept_again['last_sweep_at']}"
    )
    assert swept_again["status"] == "PRIMARY_ENGAGED", (
        f"the no-op sweep moves no state, got {swept_again['status']}"
    )

    still_open, _ = validate_paginated(api.list_typing_requests(backup_id, OPERATIONS))
    assert still_open[0]["status"] == "REQUESTED", (
        "the backup's request is not yet due at 2026-08-10T00:00:00Z, got "
        f"{still_open[0]['status']}"
    )
    replayed, _ = validate_paginated(api.list_typing_requests(primary_id, OPERATIONS))
    assert replayed[0]["status"] == "EXPIRED"
    assert _instant(replayed[0]["expired_by_sweep_at"]) == _utc(first_sweep_at), (
        "a terminal row lies outside the sweep's input set, so its expired_by_sweep_at "
        f"must still be {first_sweep_at}, got {replayed[0]['expired_by_sweep_at']}"
    )
