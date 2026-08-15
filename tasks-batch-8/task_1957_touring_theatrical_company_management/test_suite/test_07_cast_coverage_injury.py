"""Cast, tracks, coverage bench, and the injury fork/cascade (PRD §3.9, §3.10)."""
from test_helpers import (
    ApiErrorId,
    COMPANY_MANAGER,
    add_passing_check,
    add_stop,
    advance_stop,
    certify_stop,
    contract_stop,
    create_cast_member,
    create_contracted_member,
    create_coverage,
    create_tour,
    create_track,
    create_venue,
    get_cast_member,
    get_success_data,
    get_track,
    play_performance,
    report_injury,
    resolve_injury,
    schedule_performance,
    setup_principal_with_understudy,
    setup_ready_stop,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_coverage_requires_member_contracted_rejects_offered(api):
    """PRD §3.9: "The covering member must likewise be `CONTRACTED` on the same
    tour."
    PRD §3.9: "in either case the referenced member must be `CONTRACTED` and
    belong to the same tour — otherwise `ERR_PRINCIPAL_NOT_CONTRACTED`"

    Design: Difficulty/cross_entity_state_dependency/coverage_requires_member_contracted
    """
    tour = create_tour()
    member = create_cast_member(tour["id"], name="U1", contract_type="UNDERSTUDY",
                                weekly_salary_cents=500_000)  # stays OFFERED
    track = create_track(tour["id"], track_name="Lead", required_covers=1)

    resp = api.create_coverage(track["id"], {"cast_member_id": member["id"],
                                             "kind": "UNDERSTUDY", "priority_rank": 1},
                               COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_PRINCIPAL_NOT_CONTRACTED)


def test_coverage_requires_member_contracted_accepts_contracted(api):
    """PRD §3.9: "The covering member must likewise be `CONTRACTED` on the same
    tour."
    PRD §3.9: "A new coverage stands at `STANDBY`."

    Design: Difficulty/cross_entity_state_dependency/coverage_requires_member_contracted
    """
    tour = create_tour()
    member = create_contracted_member(tour["id"], name="U1", contract_type="UNDERSTUDY",
                                      weekly_salary_cents=500_000)
    track = create_track(tour["id"], track_name="Lead", required_covers=1)

    resp = api.create_coverage(track["id"], {"cast_member_id": member["id"],
                                             "kind": "UNDERSTUDY", "priority_rank": 1},
                               COMPANY_MANAGER)
    created = validate_success(resp, 201)
    assert created["status"] == "STANDBY"
    assert created["cast_member_id"] == member["id"]


def test_injury_fork_covered_branch(api):
    """PRD §3.10: "When the pool yields a candidate, the event takes the `COVERED` branch: the injured member moves from `CONTRACTED` to `ON_LEAVE`; that leave suspends the member’s own `STANDBY` and `ACTIVATED` coverages on other tracks, each suspension recomputing its track’s bench; the selected coverage flips from `STANDBY` to `ACTIVATED` and is recorded on the event as `covered_by_coverage_id`; and the activated coverage’s track recomputes — an activated cover is not an available cover, so the track may become `exposed`."

    Design: Difficulty/non_linear_state_machine/injury_branching_fork
    """
    ctx = setup_principal_with_understudy()
    inj = report_injury(ctx["principal"]["id"], "ankle")

    assert inj["status"] == "COVERED"
    assert inj["covered_by_coverage_id"] == ctx["coverage"]["id"]
    assert get_cast_member(ctx["principal"]["id"])["status"] == "ON_LEAVE"


def test_injury_fork_replaced_branch(api):
    """PRD §3.10: "When the pool is empty, the event takes the `REPLACED` branch
    instead — but only if the injured member actually is the principal of some
    track of the tour; an injury on a non-principal member with no coverage path
    is rejected with `ERR_PRINCIPAL_NOT_CONTRACTED`."
    PRD §3.10: "In this branch the member moves directly from `CONTRACTED` to
    `REPLACED`, skipping `ON_LEAVE` entirely; no coverage is activated;
    `covered_by_coverage_id` stays null"

    Design: Difficulty/non_linear_state_machine/injury_branching_fork
    """
    tour = create_tour()
    p1 = create_contracted_member(tour["id"], name="P1", weekly_salary_cents=800_000)
    p2 = create_contracted_member(tour["id"], name="P2", weekly_salary_cents=700_000)
    create_track(tour["id"], track_name="Lead", required_covers=1,
                 principal_member_id=p1["id"])
    create_track(tour["id"], track_name="Villain", required_covers=1,
                 principal_member_id=p2["id"])

    # P2's track has an empty coverage pool: the fork takes REPLACED.
    inj = report_injury(p2["id"], "voice")
    assert inj["status"] == "REPLACED"
    assert inj.get("covered_by_coverage_id") is None
    assert get_cast_member(p2["id"])["status"] == "REPLACED"


def test_injury_cascade_leave_activation_suspension(api):
    """PRD §3.10: "When the pool yields a candidate, the event takes the `COVERED` branch: the injured member moves from `CONTRACTED` to `ON_LEAVE`; that leave suspends the member’s own `STANDBY` and `ACTIVATED` coverages on other tracks, each suspension recomputing its track’s bench; the selected coverage flips from `STANDBY` to `ACTIVATED` and is recorded on the event as `covered_by_coverage_id`"

    Design: Difficulty/transitive_cascade/injury_coverage_exposure_cascade
    """
    tour = create_tour()
    p1 = create_contracted_member(tour["id"], name="P1", weekly_salary_cents=800_000)
    p2 = create_contracted_member(tour["id"], name="P2", weekly_salary_cents=700_000)
    u1 = create_contracted_member(tour["id"], name="U1", contract_type="UNDERSTUDY",
                                  weekly_salary_cents=500_000)
    t1 = create_track(tour["id"], track_name="Lead", required_covers=1,
                      principal_member_id=p1["id"])
    t2 = create_track(tour["id"], track_name="Villain", required_covers=1,
                      principal_member_id=p2["id"])
    cov1 = create_coverage(t1["id"], u1["id"], kind="UNDERSTUDY", priority_rank=1)
    cov2 = create_coverage(t2["id"], p1["id"], kind="UNDERSTUDY", priority_rank=1)

    inj = report_injury(p1["id"], "ankle")
    assert inj["status"] == "COVERED", "Link 0: selector found U1 on the principal track"
    assert get_cast_member(p1["id"])["status"] == "ON_LEAVE", "Link 1: leave"

    cov1_after = get_success_data(api.list_track_coverages(t1["id"], COMPANY_MANAGER))[0]
    cov2_after = get_success_data(api.list_track_coverages(t2["id"], COMPANY_MANAGER))[0]
    assert cov1_after["id"] == cov1["id"] and cov1_after["status"] == "ACTIVATED", (
        "Link 2: the selected coverage activates"
    )
    assert cov2_after["id"] == cov2["id"] and cov2_after["status"] == "SUSPENDED", (
        "Link 1b: the injured member's own cover on the sibling track suspends"
    )


def test_injury_cascade_track_exposure(api):
    """PRD §3.9: "A track’s `available_covers` counts its coverages standing at `STANDBY` whose cast member is `CONTRACTED`."
    PRD §3.9: "A track is `exposed` when its available covers fall below
    `required_covers` — with the caveat that a track requiring zero covers is
    never exposed."
    PRD §3.10: "the activated coverage’s track recomputes — an activated cover is
    not an available cover, so the track may become `exposed`."

    Design: Difficulty/transitive_cascade/injury_coverage_exposure_cascade
    """
    tour = create_tour()
    p1 = create_contracted_member(tour["id"], name="P1", weekly_salary_cents=800_000)
    p2 = create_contracted_member(tour["id"], name="P2", weekly_salary_cents=700_000)
    u1 = create_contracted_member(tour["id"], name="U1", contract_type="UNDERSTUDY",
                                  weekly_salary_cents=500_000)
    t1 = create_track(tour["id"], track_name="Lead", required_covers=1,
                      principal_member_id=p1["id"])
    t2 = create_track(tour["id"], track_name="Villain", required_covers=1,
                      principal_member_id=p2["id"])
    create_coverage(t1["id"], u1["id"], kind="UNDERSTUDY", priority_rank=1)
    create_coverage(t2["id"], p1["id"], kind="UNDERSTUDY", priority_rank=1)

    report_injury(p1["id"], "ankle")

    t1_after = get_track(t1["id"])
    t2_after = get_track(t2["id"])
    assert t1_after["available_covers"] == 0 and t1_after["exposed"] is True, (
        "Link 3: the ACTIVATED cover is no longer available"
    )
    assert t2_after["available_covers"] == 0 and t2_after["exposed"] is True, (
        "Link 2b->3b: the SUSPENDED cover is no longer available"
    )


def test_selector_ranking_kind_then_rank(api):
    """PRD §3.10: "It ranks candidates with understudies before swings, then by ascending `priority_rank`, then — the final tie-break — by ascending creation time; the coverage’s `id` is never used in ranking."

    Design: Corner/calculations/selector_ranking_kind_then_rank
    """
    tour = create_tour()
    p = create_contracted_member(tour["id"], name="P", weekly_salary_cents=800_000)
    s = create_contracted_member(tour["id"], name="S", contract_type="SWING",
                                 weekly_salary_cents=400_000)
    u1 = create_contracted_member(tour["id"], name="U1", contract_type="UNDERSTUDY",
                                  weekly_salary_cents=500_000)
    u2 = create_contracted_member(tour["id"], name="U2", contract_type="UNDERSTUDY",
                                  weekly_salary_cents=500_000)
    track = create_track(tour["id"], track_name="Lead", required_covers=2,
                         principal_member_id=p["id"])
    create_coverage(track["id"], s["id"], kind="SWING", priority_rank=1)
    create_coverage(track["id"], u1["id"], kind="UNDERSTUDY", priority_rank=2)
    cov_u2 = create_coverage(track["id"], u2["id"], kind="UNDERSTUDY", priority_rank=1)

    inj = report_injury(p["id"], "ankle")
    assert inj["status"] == "COVERED"
    assert inj["covered_by_coverage_id"] == cov_u2["id"], (
        "Kind ordering beats the rank-1 SWING; rank ASC beats the rank-2 UNDERSTUDY"
    )


def test_bump_pay_accrual_and_zero_bound(api):
    """PRD §3.10: "Each performance marked `PLAYED` while a coverage stands at `ACTIVATED` accrues one show to the covering member’s `bump_shows_accrued`, and `bump_pay_cents` is the accrued show count multiplied by a per-show unit: the weekly salary of the track’s principal — the member recorded as `principal_member_id` — divided by eight, rounded half-up to whole cents."
    PRD §3.10: "A member with no covered shows has a bump pay of zero."

    Design: Corner/calculations/bump_pay_accrual_and_zero_bound
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    tour_id = ctx["tour"]["id"]
    p = create_contracted_member(tour_id, name="P", weekly_salary_cents=800_000)
    u = create_contracted_member(tour_id, name="U", contract_type="UNDERSTUDY",
                                 weekly_salary_cents=500_000)
    track = create_track(tour_id, track_name="Lead", required_covers=1,
                         principal_member_id=p["id"])
    create_coverage(track["id"], u["id"], kind="UNDERSTUDY", priority_rank=1)
    perf1 = schedule_performance(stop_id, perf_date="2026-09-08")
    perf2 = schedule_performance(stop_id, perf_date="2026-09-09")
    perf3 = schedule_performance(stop_id, perf_date="2026-09-10")

    inj = report_injury(p["id"], "ankle")
    assert inj["status"] == "COVERED"

    play_performance(perf1["id"], 100_000)
    play_performance(perf2["id"], 100_000)
    mid = get_cast_member(u["id"])
    # Per-show unit: round(800,000 / 8) = 100,000; two covered shows.
    assert mid["bump_shows_accrued"] == 2
    assert mid["bump_pay_cents"] == 200_000

    resolve_injury(inj["id"])  # coverage returns to STANDBY
    play_performance(perf3["id"], 100_000)
    end = get_cast_member(u["id"])
    assert end["bump_shows_accrued"] == 2
    assert end["bump_pay_cents"] == 200_000, (
        "A STANDBY coverage accrues nothing; the zero-bound stays intact"
    )


def test_duplicate_cover_rank_returns_duplicate_record(api):
    """PRD §3.9: "the rank must be unique among the non-`RELEASED` coverages of
    the same track and kind, a collision drawing `ERR_DUPLICATE_RECORD`."

    Design: Corner/validations/duplicate_cover_rank_returns_duplicate_record
    """
    tour = create_tour()
    u1 = create_contracted_member(tour["id"], name="U1", contract_type="UNDERSTUDY",
                                  weekly_salary_cents=500_000)
    u2 = create_contracted_member(tour["id"], name="U2", contract_type="UNDERSTUDY",
                                  weekly_salary_cents=500_000)
    track = create_track(tour["id"], track_name="Lead", required_covers=2)
    create_coverage(track["id"], u1["id"], kind="UNDERSTUDY", priority_rank=1)

    resp = api.create_coverage(track["id"], {"cast_member_id": u2["id"],
                                             "kind": "UNDERSTUDY", "priority_rank": 1},
                               COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECORD)


def test_principal_double_booked_returns_error(api):
    """PRD §3.9: "no member may be principal of more than one track of the tour,
    else `ERR_PRINCIPAL_DOUBLE_BOOKED`."

    Design: Corner/validations/principal_double_booked_returns_error
    """
    tour = create_tour()
    p = create_contracted_member(tour["id"], name="P", weekly_salary_cents=800_000)
    create_track(tour["id"], track_name="Lead", required_covers=1,
                 principal_member_id=p["id"])
    t2 = create_track(tour["id"], track_name="Villain", required_covers=1)

    resp = api.patch_track(t2["id"], {"principal_member_id": p["id"]}, COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_PRINCIPAL_DOUBLE_BOOKED)


def test_cast_invalid_transitions(api):
    """PRD §3.9: "A new member is `OFFERED`; signing moves them to `CONTRACTED` —
    a transition legal only from `OFFERED`, else `ERR_CAST_INVALID_STATE`."
    PRD §3.10: "The member must be `CONTRACTED` — reporting on anyone else is
    `ERR_CAST_INVALID_STATE`"

    Design: Corner/state_machines/cast_invalid_transitions
    """
    tour = create_tour()
    a = create_contracted_member(tour["id"], name="A", weekly_salary_cents=800_000)
    b = create_cast_member(tour["id"], name="B", contract_type="UNDERSTUDY",
                           weekly_salary_cents=500_000)  # stays OFFERED

    resp1 = api.put_cast(a["id"], {"status": "CONTRACTED"}, COMPANY_MANAGER)
    validate_error(resp1, ApiErrorId.ERR_CAST_INVALID_STATE)

    resp2 = api.create_injury(b["id"], {"notes": "flu"}, COMPANY_MANAGER)
    validate_error(resp2, ApiErrorId.ERR_CAST_INVALID_STATE)


def test_coverage_release_activated_returns_invalid_state(api):
    """PRD §3.9: "A coverage may be released from `STANDBY` by the
    `CompanyManager`; releasing an `ACTIVATED` coverage — one currently covering
    an open injury — is rejected with `ERR_COVERAGE_ACTIVATED`."

    Design: Corner/state_machines/coverage_release_activated_returns_invalid_state
    """
    ctx = setup_principal_with_understudy()
    report_injury(ctx["principal"]["id"], "ankle")  # activates the coverage

    resp = api.put_coverage(ctx["coverage"]["id"], {"status": "RELEASED"},
                            COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_ACTIVATED)


def test_cast_release_while_covering_rejected(api):
    """PRD §3.9: "Releasing an entire cast member, also a `CompanyManager` action, is legal from `OFFERED`, `CONTRACTED`, or `ON_LEAVE`, but is blocked while any of the member’s coverages stands at `ACTIVATED` (again `ERR_COVERAGE_ACTIVATED`); on release, the member’s `STANDBY` and `SUSPENDED` coverages are released with them, and every affected track recomputes."

    Design: Corner/state_machines/cast_release_while_covering_rejected
    """
    ctx = setup_principal_with_understudy()
    report_injury(ctx["principal"]["id"], "ankle")  # understudy now ACTIVATED

    resp = api.put_cast(ctx["understudy"]["id"], {"status": "RELEASED"},
                        COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_ACTIVATED)


def test_injury_resolve_replaced_returns_invalid_state(api):
    """PRD §3.10: "Resolution — by the `CompanyManager`, and only from `COVERED`,
    anything else drawing `ERR_INJURY_INVALID_STATE`"
    PRD §3.10: "`RESOLVED` and `REPLACED` are terminal states for an injury
    event."

    Design: Corner/state_machines/injury_resolve_replaced_returns_invalid_state
    """
    tour = create_tour()
    p = create_contracted_member(tour["id"], name="P", weekly_salary_cents=800_000)
    create_track(tour["id"], track_name="Lead", required_covers=0,
                 principal_member_id=p["id"])

    inj = report_injury(p["id"], "vocal rest")
    assert inj["status"] == "REPLACED", "Empty coverage pool takes the REPLACED branch"

    resp = api.put_injury(inj["id"], {"status": "RESOLVED"}, COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INJURY_INVALID_STATE)


def test_second_open_injury_returns_duplicate_record(api):
    """PRD §3.10: "The member must be `CONTRACTED` — reporting on anyone else is
    `ERR_CAST_INVALID_STATE` — and no member may carry two open injuries: one
    injury in `COVERED` per member at a time, a second report drawing
    `ERR_DUPLICATE_RECORD`."

    The prose names `ERR_DUPLICATE_RECORD` for the second report while the
    pipeline's state guard (the member is ON_LEAVE once COVERED) also applies;
    either rejection honors the contract.

    Design: Corner/validations/second_open_injury_returns_duplicate_record
    """
    ctx = setup_principal_with_understudy()
    report_injury(ctx["principal"]["id"], "ankle")  # COVERED, member ON_LEAVE

    resp = api.create_injury(ctx["principal"]["id"],
                             {"notes": "second incident while out"}, COMPANY_MANAGER)
    validate_error_is_one_of(resp, [ApiErrorId.ERR_DUPLICATE_RECORD,
                                    ApiErrorId.ERR_CAST_INVALID_STATE])


def test_track_principal_replacement_after_replaced(api):
    """PRD §3.10: "In this branch the member moves directly from `CONTRACTED` to `REPLACED`, skipping `ON_LEAVE` entirely; no coverage is activated; `covered_by_coverage_id` stays null; and the principal’s track keeps its `principal_member_id` pointing at the replaced member until the `CompanyManager` assigns a successor, its exposure recomputing against the vacant bench."
    PRD §3.9: "`REPLACED` and `RELEASED` are terminal for a cast member."

    Design: Corner/state_machines/track_principal_replacement_after_replaced
    """
    tour = create_tour()
    p = create_contracted_member(tour["id"], name="P", weekly_salary_cents=800_000)
    s = create_contracted_member(tour["id"], name="S", weekly_salary_cents=750_000)
    track = create_track(tour["id"], track_name="Lead", required_covers=1,
                         principal_member_id=p["id"])
    report_injury(p["id"], "vocal rest")  # REPLACED branch (no coverage)

    patched = validate_success(
        api.patch_track(track["id"], {"principal_member_id": s["id"]}, COMPANY_MANAGER))
    assert patched["principal_member_id"] == s["id"]

    assert get_cast_member(p["id"])["status"] == "REPLACED", (
        "The replaced member is terminal; PATCH does not resurrect them"
    )
