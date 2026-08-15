"""Meal counts, day close/reconcile, and monthly meal reimbursement claims."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_day,
    create_active_member,
    create_claim,
    create_claim_payload,
    create_meal_counts_payload,
    director_headers,
    get_club_day,
    make_reviewer_headers,
    open_club_day,
    run_day,
    set_meal_counts,
    setup_site_with_director,
    setup_submitted_claim,
    sign_in_member,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
    walker_sign_out,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_three_walkers(api):
    """Site + director + three FREE-tier ACTIVE members with walker_ok."""
    site, director = setup_site_with_director(clock="2026-08-01T09:00:00Z")
    members = [
        create_active_member(site["id"], director["id"], legal_name=n,
                             walker_ok=True)
        for n in ("Kid One", "Kid Two", "Kid Three")
    ]
    return site, director, members


def _setup_provisional_divergence(api):
    """08-03 RECONCILED with BREAKFAST FREE 3; 08-04 CLOSED (not reconciled)
    with BREAKFAST FREE 3; claim for 2026-08 created. Each line rounds to
    round(3 x 225 x 1.10) = 743. Returns (site, director, claim)."""
    site, director, members = _setup_three_walkers(api)
    ids = [m["id"] for m in members]
    run_day(site["id"], director["id"], "2026-08-03", member_ids=ids,
            meal_counts={"meal_type": "BREAKFAST", "free_count": 3},
            walker_sign_out=True, close=True, reconcile=True)
    run_day(site["id"], director["id"], "2026-08-04", member_ids=ids,
            meal_counts={"meal_type": "BREAKFAST", "free_count": 3},
            walker_sign_out=True, close=True, reconcile=False)
    claim = create_claim(site["id"], director["id"], "2026-08")
    return site, director, claim


def test_claim_provisional_includes_closed_day(api):
    """PRD 3.9: "At creation the server pins a `rate_snapshot` — the site's
    `meal_rates_cents` plus, per day, a seasonal multiplier of 1.10 for days
    falling in June, July, or August and 1.0 for all other months — and
    computes `provisional_total_cents` over the month's club days in `CLOSED`
    or `RECONCILED` status."

    Design: Difficulty/dual_variant_calc/meal_claim_provisional_includes_closed_final_requires_reconciled
    """
    site, director, claim = _setup_provisional_divergence(api)
    # both days count provisionally: 743 (reconciled day) + 743 (closed day)
    assert claim["provisional_total_cents"] == 1486
    assert claim["status"] == "DRAFT"
    assert claim["final_total_cents"] is None


def test_claim_final_requires_reconciled_days(api):
    """PRD 3.9: "Submission computes `final_total_cents` by the same per-line
    rounding rule but over `RECONCILED` days only, still using the pinned
    `rate_snapshot`; the final total therefore diverges from the provisional
    one whenever a counted day was `CLOSED` but not yet `RECONCILED` at
    creation. The submitter's `X-User-ID` is recorded as
    `submitted_by_user_id` and the claim becomes `SUBMITTED`."

    Design: Difficulty/dual_variant_calc/meal_claim_provisional_includes_closed_final_requires_reconciled
    """
    site, director, claim = _setup_provisional_divergence(api)
    submitted = submit_claim(claim["id"], director["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["final_total_cents"] == 743, (
        "only the RECONCILED day counts in the FINAL variant"
    )
    assert submitted["final_total_cents"] != submitted["provisional_total_cents"]
    assert submitted["submitted_by_user_id"] == director["id"]


def _setup_two_reconciled_days(api):
    """08-03 and 08-04 BOTH RECONCILED, each with BREAKFAST FREE 3.
    Returns (site, director)."""
    site, director, members = _setup_three_walkers(api)
    ids = [m["id"] for m in members]
    for date in ("2026-08-03", "2026-08-04"):
        run_day(site["id"], director["id"], date, member_ids=ids,
                meal_counts={"meal_type": "BREAKFAST", "free_count": 3},
                walker_sign_out=True, close=True, reconcile=True)
    return site, director


def test_claim_per_line_rounding_final(api):
    """PRD 3.9: "The computation works line by line: for each included day,
    meal type, and tier, the served count is multiplied by the snapshotted rate
    for that meal type and tier and by the day's snapshotted seasonal
    multiplier, and the line is rounded half-up to whole cents; the provisional
    total is the sum of those individually rounded lines. Summing first and
    rounding once at the end is not the rule."

    Design: Difficulty/combinatorial_formula/meal_claim_per_line_rounding_beats_sum_then_round
    """
    site, director = _setup_two_reconciled_days(api)
    claim = create_claim(site["id"], director["id"], "2026-08")
    submitted = submit_claim(claim["id"], director["id"])
    # per line: round(3 x 225 x 1.10) = round(742.5) = 743; two lines -> 1486.
    # The forbidden sum-then-round order would give round(1485.0) = 1485.
    assert submitted["final_total_cents"] == 1486
    assert submitted["final_total_cents"] != 1485


def test_claim_per_line_rounding_provisional(api):
    """PRD 3.9: "the line is rounded half-up to whole cents; the provisional
    total is the sum of those individually rounded lines."

    Design: Difficulty/combinatorial_formula/meal_claim_per_line_rounding_beats_sum_then_round
    """
    site, director = _setup_two_reconciled_days(api)
    claim = create_claim(site["id"], director["id"], "2026-08")
    assert claim["provisional_total_cents"] == 1486, (
        "two individually rounded 743-cent lines sum to 1486, not 1485"
    )


def _setup_closed_only_claim(api):
    """One club day 2026-08-03 CLOSED (never reconciled) with BREAKFAST FREE 1;
    a DRAFT claim for 2026-08. Returns (site, director, claim)."""
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A",
                                  walker_ok=True)
    run_day(site["id"], director["id"], "2026-08-03", member_ids=[member["id"]],
            meal_counts={"meal_type": "BREAKFAST", "free_count": 1},
            walker_sign_out=True, close=True, reconcile=False)
    claim = create_claim(site["id"], director["id"], "2026-08")
    return site, director, claim


def test_claim_submit_blocked_without_reconciled_days(api):
    """PRD 3.9: "Submitting the claim — a `SiteDirector` action — requires
    `DRAFT` (`ERR_CLAIM_NOT_SUBMITTABLE`) and at least one `RECONCILED` club
    day in the claim month (`ERR_CLAIM_NO_RECONCILED_DAYS`, 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_without_reconciled_club_days
    """
    site, director, claim = _setup_closed_only_claim(api)
    res = api.submit_meal_claim(claim["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_CLAIM_NO_RECONCILED_DAYS,
                   expected_status=409)
    data, _ = validate_paginated(api.list_meal_claims(site["id"], ADMIN))
    assert data[0]["status"] == "DRAFT"
    assert data[0]["final_total_cents"] is None


def test_claim_provisional_counts_closed_day_when_submit_blocked(api):
    """PRD 3.9: "computes `provisional_total_cents` over the month's club days
    in `CLOSED` or `RECONCILED` status" — the CLOSED-but-not-RECONCILED day
    still counts toward the provisional total: round(1 x 225 x 1.10) = 248.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_without_reconciled_club_days
    """
    site, director, claim = _setup_closed_only_claim(api)
    assert claim["provisional_total_cents"] == 248
    api.submit_meal_claim(claim["id"], director_headers(director))
    data, _ = validate_paginated(api.list_meal_claims(site["id"], ADMIN))
    assert data[0]["provisional_total_cents"] == 248


def test_claim_submit_twice_returns_not_submittable(api):
    """PRD 3.9: "Submitting the claim — a `SiteDirector` action — requires
    `DRAFT` (`ERR_CLAIM_NOT_SUBMITTABLE`)".

    Design: Corner/state_machines/c_claim_submit_twice_returns_not_submittable
    """
    ctx = setup_submitted_claim(free_count=1)
    assert ctx["claim"]["final_total_cents"] == 248
    res = api.submit_meal_claim(ctx["claim"]["id"],
                                director_headers(ctx["director"]))
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_SUBMITTABLE, expected_status=409)
    data, _ = validate_paginated(
        api.list_meal_claims(ctx["site"]["id"], ADMIN)
    )
    assert data[0]["status"] == "SUBMITTED"
    assert data[0]["final_total_cents"] == 248, (
        "the rejected second submit does not recompute the final total"
    )


def test_claim_approve_draft_returns_not_submitted(api):
    """PRD 3.9: "the claim must be `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`)".

    Design: Corner/state_machines/c_claim_approve_draft_returns_not_submitted
    """
    site, director = setup_site_with_director()
    claim = create_claim(site["id"], director["id"], "2026-08")
    res = api.approve_meal_claim(claim["id"], make_reviewer_headers("reviewer-1"))
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED, expected_status=409)
    data, _ = validate_paginated(api.list_meal_claims(site["id"], ADMIN))
    assert data[0]["status"] == "DRAFT"


def test_claim_duplicate_month_rejected(api):
    """PRD 3.9: "one claim per site per month (`ERR_DUPLICATE_CLAIM_MONTH`,
    409)".

    Design: Corner/errors/c_claim_duplicate_month_rejected
    """
    site, director = setup_site_with_director()
    create_claim(site["id"], director["id"], "2026-08")
    res = api.create_meal_claim(create_claim_payload(site["id"], "2026-08"),
                                director_headers(director))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CLAIM_MONTH, expected_status=409)


def test_meal_counts_exceed_attendance_at_entry(api):
    """PRD 3.5: "Every tier count is validated at entry: it may not exceed the
    number of the day's attendance records in `ON_SITE` or `SIGNED_OUT` whose
    member's `eligibility_tier` matches that tier, or the write is rejected
    with `ERR_MEAL_COUNTS_EXCEED_ATTENDANCE` (422)."

    Design: Corner/validations/c_meal_counts_exceed_attendance_at_entry
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    sign_in_member(day["id"], member["id"], director["id"])
    res = api.upsert_meal_counts(
        day["id"],
        create_meal_counts_payload("BREAKFAST", free_count=2),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_MEAL_COUNTS_EXCEED_ATTENDANCE,
                   expected_status=422)
    day_after = get_club_day(day["id"])
    assert day_after["meal_counts"]["BREAKFAST"]["FREE"] == 0


def test_reconcile_fails_when_counts_exceed_final_signed_out(api):
    """PRD 3.9: "Reconciliation re-validates the meal tally strictly: for every
    meal type and every tier, the recorded count in `meal_counts` may not
    exceed the number of the day's attendance records in `SIGNED_OUT` whose
    member's `eligibility_tier` matches that tier, or the reconcile is rejected
    with `ERR_MEAL_COUNTS_EXCEED_ATTENDANCE`."

    Design: Corner/validations/c_reconcile_fails_when_counts_exceed_final_signed_out
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    sign_in_member(day["id"], member["id"], director["id"])
    # passes at entry: 1 ON_SITE FREE record covers count 1
    set_meal_counts(day["id"], director["id"], "BREAKFAST", free_count=1)
    # no sign-out: close sweeps the record to MISSING_SIGNOUT
    close_day(day["id"], director["id"])
    res = api.reconcile_club_day(day["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_MEAL_COUNTS_EXCEED_ATTENDANCE,
                   expected_status=422)
    assert get_club_day(day["id"])["status"] == "CLOSED"


def test_meal_counts_after_reconcile_returns_day_locked(api):
    """PRD 3.5: "Posting counts against a day that is no longer `OPEN` is
    rejected with `ERR_CLUB_DAY_NOT_OPEN` — except a `RECONCILED` day, which
    answers with `ERR_DAY_LOCKED`."

    Design: Corner/state_machines/c_meal_counts_after_reconcile_returns_day_locked
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A",
                                  walker_ok=True)
    run_day(site["id"], director["id"], "2026-08-03", member_ids=[member["id"]],
            meal_counts={"meal_type": "BREAKFAST", "free_count": 1},
            walker_sign_out=True, close=True, reconcile=True)
    days, _ = validate_paginated(api.list_club_days(site["id"], ADMIN))
    day_id = days[0]["id"]
    assert days[0]["status"] == "RECONCILED"
    res = api.upsert_meal_counts(
        day_id,
        create_meal_counts_payload("SNACK", free_count=1),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_DAY_LOCKED, expected_status=409)
    day_after = get_club_day(day_id)
    assert day_after["meal_counts"]["SNACK"]["FREE"] == 0
    assert day_after["meal_counts"]["BREAKFAST"]["FREE"] == 1


def test_reconcile_open_day_returns_not_closed(api):
    """PRD 3.9: "Reconciling a closed day — again a `SiteDirector` action —
    requires the day `CLOSED` (`ERR_CLUB_DAY_NOT_CLOSED`)."

    Design: Corner/state_machines/c_reconcile_open_day_returns_not_closed
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    res = api.reconcile_club_day(day["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_CLUB_DAY_NOT_CLOSED, expected_status=409)
    assert get_club_day(day["id"])["status"] == "OPEN"


def test_claim_segregation_of_duties(api):
    """PRD 3.9: "Approval belongs to the external `StateAgencyReviewer`: the
    claim must be `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`) and the approver's
    `X-User-ID` must differ from `submitted_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`, 403). Approval records `approved_by_user_id`
    and moves the claim to `APPROVED`."

    Design: Corner/rbac/c_claim_segregation_of_duties
    """
    ctx = setup_submitted_claim(free_count=1)
    claim = ctx["claim"]
    assert claim["submitted_by_user_id"] == ctx["director"]["id"]

    # a reviewer presenting the submitter's user id is rejected
    res = api.approve_meal_claim(
        claim["id"], make_reviewer_headers(ctx["director"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    approved = validate_success(
        api.approve_meal_claim(claim["id"], make_reviewer_headers("reviewer-1")),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "reviewer-1"
    assert approved["submitted_by_user_id"] == ctx["director"]["id"]
    assert approved["final_total_cents"] == 248
