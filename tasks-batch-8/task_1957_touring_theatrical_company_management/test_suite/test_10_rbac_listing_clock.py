"""Role authorization, list endpoints, FK reverse reachability, logical clock
(PRD §2.1, §2.3, §2.7, §2.9)."""
from test_helpers import (
    ApiErrorId,
    COMPANY_MANAGER,
    NON_EXISTENT_UUID,
    PRODUCER,
    TOUR_MANAGER,
    TREASURER,
    add_stop,
    build_user_headers,
    create_contracted_member,
    create_coverage,
    create_tour,
    create_tour_payload,
    create_track,
    create_venue,
    create_venue_payload,
    issue_per_diem,
    make_tour_manager_headers,
    report_injury,
    schedule_performance,
    setup_ready_stop,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_rbac_role_denials_matrix(api):
    """PRD §2.1: "A request whose declared role is not authorized for the target
    endpoint — or, on shared transition endpoints, for the specific transition
    requested — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.8: "A `Producer` may cancel a stop standing at `TENTATIVE`,
    `CONTRACTED`, `ADVANCED`, or `READY`."
    PRD §3.3: "During the advance — that is, while a stop is `CONTRACTED` or `ADVANCED` (creation at any other time is `ERR_STOP_INVALID_STATE`) — a `TourManager` registers the production’s technical rider checks against the venue."
    PRD §3.4: "The `Treasurer` marks it `PLAYED`, recording the performance’s
    `gross_cents`"
    PRD §3.6: "A statement is `ISSUED` on creation; the `CompanyManager` later
    marks it `PAID`"
    PRD §3.1: "A `Producer` registers each venue with its `name`, `city`, and the
    four technical specifications the rider will later be checked against"

    Design: Corner/rbac/rbac_role_denials_matrix
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    tour_id = ctx["tour"]["id"]
    perf = schedule_performance(stop_id, perf_date="2026-09-08")
    member = create_contracted_member(tour_id, name="Pat P")
    pd = issue_per_diem(stop_id, member["id"], days_present=7, travel_days=0)

    # CANCELLED is a Producer-only transition on the shared stop endpoint.
    validate_error(api.put_stop(stop_id, {"status": "CANCELLED"}, TOUR_MANAGER),
                   ApiErrorId.ERR_FORBIDDEN)
    # Tech-check creation is TourManager-only.
    validate_error(api.create_tech_check(stop_id, {"item": "FLY_LINES",
                                                   "required_value": 10}, PRODUCER),
                   ApiErrorId.ERR_FORBIDDEN)
    # PLAYED is the Treasurer's marking on the shared performance endpoint.
    validate_error(api.put_performance(perf["id"], {"status": "PLAYED",
                                                    "gross_cents": 100}, TOUR_MANAGER),
                   ApiErrorId.ERR_FORBIDDEN)
    # Per-diem pay is CompanyManager-only.
    validate_error(api.put_per_diem(pd["id"], {"status": "PAID"}, TREASURER),
                   ApiErrorId.ERR_FORBIDDEN)
    # Venue creation is Producer-only.
    validate_error(api.create_venue(create_venue_payload(name="V2", city="Boston"),
                                    COMPANY_MANAGER),
                   ApiErrorId.ERR_FORBIDDEN)
    # Tour creation is Producer-only.
    validate_error(api.create_tour(create_tour_payload(name="Tour Z"), TREASURER),
                   ApiErrorId.ERR_FORBIDDEN)


def test_rbac_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is absent or whose value
    is not one of these four role names is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/rbac_missing_auth_header_returns_unauthenticated
    """
    tour = create_tour()

    no_role = api.get_tour(tour["id"], headers={"X-User-ID": "u1"})
    validate_error(no_role, ApiErrorId.ERR_UNAUTHENTICATED)

    bad_role = api.get_tour(tour["id"], headers=build_user_headers("u1", "Nobody"))
    validate_error(bad_role, ApiErrorId.ERR_UNAUTHENTICATED)


def test_list_pagination_and_filtering(api):
    """PRD §2.3: "The `meta` object of a list response carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: GET /stops is "List stops; filterable by `tour_id`, `venue_id`,
    `status`".

    Design: Corner/endpoints/list_pagination_and_filtering
    """
    tour_a = create_tour(name="Tour A")
    tour_b = create_tour(name="Tour B")
    venue = create_venue()

    weeks = [("2026-09-07", "2026-09-13", "2026-09-05"),
             ("2026-09-15", "2026-09-20", "2026-09-14"),
             ("2026-09-22", "2026-09-27", "2026-09-21")]
    a_ids = []
    for start, end, load_in in weeks:
        stop = add_stop(tour_a["id"], venue["id"], play_week_start=start,
                        play_week_end=end, load_in_date=load_in, travel_in_days=1,
                        guarantee_cents=1_000_000)
        a_ids.append(stop["id"])
    b_stop = add_stop(tour_b["id"], venue["id"], guarantee_cents=1_000_000)

    page1, meta1 = validate_paginated(api.list_stops(
        PRODUCER, params={"tour_id": tour_a["id"], "status": "TENTATIVE",
                          "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_stops(
        PRODUCER, params={"tour_id": tour_a["id"], "status": "TENTATIVE",
                          "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    seen = {row["id"] for row in page1} | {row["id"] for row in page2}
    assert seen == set(a_ids), "Pages partition tour A's stops without gaps or repeats"
    assert b_stop["id"] not in seen, "The tour_id filter isolates the tour's stops"


def test_fk_reverse_lists(api):
    """PRD §2.7: "Many resources exist only under a parent: a stop belongs to a
    tour; performances, tech-rider checks, crew calls, per-diem statements, and
    a settlement belong to a stop; cast members and character tracks belong to a
    tour; coverage assignments belong to a track; injury events belong to a cast
    member."
    PRD §4: GET /stops/{id}/settlement is "Fetch the settlement of a stop (1:1,
    returns an array of zero or one)".

    Design: Corner/endpoints/fk_reverse_lists
    """
    ctx = setup_ready_stop()
    tour_id = ctx["tour"]["id"]
    p = create_contracted_member(tour_id, name="P", weekly_salary_cents=800_000)
    u = create_contracted_member(tour_id, name="U", contract_type="UNDERSTUDY",
                                 weekly_salary_cents=500_000)
    track = create_track(tour_id, track_name="Lead", required_covers=1,
                         principal_member_id=p["id"])
    create_coverage(track["id"], u["id"], kind="UNDERSTUDY", priority_rank=1)
    report_injury(p["id"], "ankle")

    cast, cast_meta = validate_paginated(api.list_cast(tour_id, PRODUCER))
    assert len(cast) == 2, "Cast of the tour reachable in reverse"

    coverages, _ = validate_paginated(api.list_track_coverages(track["id"], PRODUCER))
    assert len(coverages) == 1
    assert coverages[0]["status"] == "ACTIVATED"

    member_coverages, _ = validate_paginated(api.list_cast_coverages(u["id"], PRODUCER))
    assert len(member_coverages) == 1

    injuries, _ = validate_paginated(api.list_injuries(p["id"], PRODUCER))
    assert len(injuries) == 1
    assert injuries[0]["status"] == "COVERED"

    # The 1:1 settlement sub-resource is an empty array before the stop closes.
    settlement_rows = validate_success(api.get_stop_settlement(ctx["stop"]["id"], PRODUCER))
    assert settlement_rows == []


def test_clock_set_endpoint_roundtrip(api):
    """PRD §2.9: "The system maintains a logical clock whose value before any
    explicit set is exactly `2026-08-01T00:00:00Z`. A `Producer` may advance the
    logical clock by supplying a `to_iso8601` instant through the clock-setting
    capability; the endpoint returns the resulting `current_utc`."

    Design: Corner/endpoints/clock_set_endpoint_roundtrip
    """
    resp = api.set_clock({"to_iso8601": "2026-08-01T12:00:00Z"}, PRODUCER)
    data = validate_success(resp)
    assert data["current_utc"] == "2026-08-01T12:00:00Z"
