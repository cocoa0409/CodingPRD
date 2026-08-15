"""Group booking supervision ratio (ceil boundary, per-chaperone cert branch)
and its priority over slot capacity (PRD §3.6, §2.6)."""
from test_helpers import (
    ApiErrorId,
    assert_group_booking,
    create_group_booking_payload,
    make_certified_chaperones,
    make_group_leader_headers,
    make_open_slot,
    make_participating_volunteer,
    make_volunteer,
    setup_full_slot_with_waitlist,
    setup_season_open,
    validate_error,
    validate_success,
)


def _booking_attempt(api, slot_id, leader, member_count, minor_count,
                     chaperone_count, chaperone_ids, org):
    payload = create_group_booking_payload(
        slot_id=slot_id,
        leader_volunteer_id=leader["id"],
        organization_name=org,
        member_count=member_count,
        minor_count=minor_count,
        chaperone_count=chaperone_count,
        chaperone_volunteer_ids=chaperone_ids,
    )
    return api.create_group_booking(payload, make_group_leader_headers(leader["id"]))


def test_supervision_ratio_ceil_with_cert_branch(api):
    """PRD §3.6: "The supervision ratio rule is precise and is evaluated both at
    creation and again at confirmation. It passes exactly when all three clauses
    hold: `chaperone_count` is at least `required_chaperones`; the count of
    distinct ids in `chaperone_volunteer_ids` — duplicates are counted once — that
    each reference an existing volunteer holding an `ACTIVE` `SUPERVISION`
    certification is at least `required_chaperones`; and `minor_count` does not
    exceed `member_count`."
    PRD §3.6: "On creation the server derives `required_chaperones` as the
    `minor_count` divided by 8 and rounded up to a whole chaperone".

    Design: Difficulty/combinatorial_formula/supervision_ratio_ceil_with_cert_branch
    """
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=40, capacity_youth=40)
    leader = make_participating_volunteer()
    c1, c2, c3 = make_certified_chaperones(3)
    c4 = make_volunteer()  # exists but holds no certification

    booking_a = validate_success(
        _booking_attempt(
            api, slot["id"], leader, 20, 17, 3, [c1["id"], c2["id"], c3["id"]],
            "School A",
        ),
        expected_status=201,
    )
    assert_group_booking(booking_a)
    assert booking_a["required_chaperones"] == 3, "ceil(17/8) == 3"
    assert booking_a["status"] == "REQUESTED"

    err = validate_error(
        _booking_attempt(
            api, slot["id"], leader, 19, 17, 2, [c1["id"], c2["id"]], "School B"
        ),
        ApiErrorId.ERR_SUPERVISION_RATIO_VIOLATION,
    )
    assert err["error_id"] == "ERR_SUPERVISION_RATIO_VIOLATION", (
        "17 minors need 3 chaperones; only 2 declared/certified"
    )

    err = validate_error(
        _booking_attempt(
            api, slot["id"], leader, 18, 16, 2, [c1["id"], c4["id"]], "School C"
        ),
        ApiErrorId.ERR_SUPERVISION_RATIO_VIOLATION,
    )
    assert err["error_id"] == "ERR_SUPERVISION_RATIO_VIOLATION", (
        "16 minors need 2 certified chaperones; the uncertified id does not count"
    )


def test_supervision_exact_multiple_boundary(api):
    """PRD §3.6: "On creation the server derives `required_chaperones` as the
    `minor_count` divided by 8 and rounded up to a whole chaperone — so 16 minors
    require exactly 2 — and the booking starts `REQUESTED` with `rejection_reason`
    null."

    Design: Difficulty/boundary_precision_check/supervision_exact_multiple_boundary
    """
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=40, capacity_youth=40)
    leader = make_participating_volunteer()
    c1, c2 = make_certified_chaperones(2)

    booking = validate_success(
        _booking_attempt(
            api, slot["id"], leader, 18, 16, 2, [c1["id"], c2["id"]], "School Exact"
        ),
        expected_status=201,
    )
    assert booking["required_chaperones"] == 2, (
        "the exact multiple of 8 does NOT round up to 3"
    )
    assert booking["status"] == "REQUESTED"

    err = validate_error(
        _booking_attempt(
            api, slot["id"], leader, 18, 16, 1, [c1["id"]], "School Short"
        ),
        ApiErrorId.ERR_SUPERVISION_RATIO_VIOLATION,
    )
    assert err["error_id"] == "ERR_SUPERVISION_RATIO_VIOLATION", "1 chaperone < 2 required"


def test_supervision_ratio_beats_slot_capacity_on_booking_create(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed global order and reports the first failure
    encountered — first match wins."
    PRD §2.6: "10. **Youth supervision.** `ERR_YOUTH_SUPERVISION_REQUIRED` and
    `ERR_SUPERVISION_RATIO_VIOLATION` (409)."
    PRD §2.6: "14. **Capacity and quota.** `ERR_SLOT_CAPACITY_EXCEEDED`,
    `ERR_YOUTH_CAPACITY_EXCEEDED`, `ERR_BED_CAPACITY_EXCEEDED`,
    `ERR_KEY_LIMIT_EXCEEDED`, `ERR_KEY_REGISTRY_FULL`, `ERR_TOOL_INSUFFICIENT_STOCK`,
    and `ERR_RECIPIENT_CAPACITY_EXCEEDED` (409)."
    PRD §3.6: "the supervision ratio must hold (otherwise
    `ERR_SUPERVISION_RATIO_VIOLATION`); and both capacity pools must pre-check".

    Design: Difficulty/priority_pair_validation_conflict/supervision_ratio_beats_slot_capacity_on_booking_create
    """
    ctx = setup_full_slot_with_waitlist(capacity_total=2, capacity_youth=2)
    slot = ctx["slot"]
    assert slot["status"] == "FULL"
    leader = make_participating_volunteer()
    (c1,) = make_certified_chaperones(1)

    # 9 minors need ceil(9/8) == 2 chaperones; only 1 certified. The booking also
    # overflows the FULL slot (2 + 10 > 2) — the safety tier must win.
    err = validate_error(
        _booking_attempt(
            api, slot["id"], leader, 10, 9, 1, [c1["id"]], "School A"
        ),
        ApiErrorId.ERR_SUPERVISION_RATIO_VIOLATION,
    )
    assert err["error_id"] == "ERR_SUPERVISION_RATIO_VIOLATION"


def test_supervision_ratio_duplicate_chaperone_ids_counted_once(api):
    """PRD §3.6: "It passes exactly when all three clauses hold: `chaperone_count`
    is at least `required_chaperones`; the count of distinct ids in
    `chaperone_volunteer_ids` — duplicates are counted once — that each reference
    an existing volunteer holding an `ACTIVE` `SUPERVISION` certification is at
    least `required_chaperones`; and `minor_count` does not exceed
    `member_count`."

    Design: Difficulty/combinatorial_formula/supervision_ratio_ceil_with_cert_branch
    """
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=40, capacity_youth=40)
    leader = make_participating_volunteer()
    c1, c2 = make_certified_chaperones(2)

    # 17 minors need ceil(17/8) == 3; the duplicated id counts once, leaving 2.
    err = validate_error(
        _booking_attempt(
            api, slot["id"], leader, 20, 17, 3, [c1["id"], c1["id"], c2["id"]],
            "School Dup",
        ),
        ApiErrorId.ERR_SUPERVISION_RATIO_VIOLATION,
    )
    assert err["error_id"] == "ERR_SUPERVISION_RATIO_VIOLATION"


def test_supervision_eight_minors_exactly_one_chaperone(api):
    """PRD §3.6: "On creation the server derives `required_chaperones` as the
    `minor_count` divided by 8 and rounded up to a whole chaperone — so 16 minors
    require exactly 2 — and the booking starts `REQUESTED` with `rejection_reason`
    null."

    Design: Difficulty/boundary_precision_check/supervision_exact_multiple_boundary
    """
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=40, capacity_youth=40)
    leader = make_participating_volunteer()
    (c1,) = make_certified_chaperones(1)

    booking = validate_success(
        _booking_attempt(
            api, slot["id"], leader, 10, 8, 1, [c1["id"]], "School Eight"
        ),
        expected_status=201,
    )
    assert booking["required_chaperones"] == 1, "ceil(8/8) == 1 exactly"
    assert booking["status"] == "REQUESTED"

    err = validate_error(
        _booking_attempt(api, slot["id"], leader, 10, 8, 0, [], "School None"),
        ApiErrorId.ERR_SUPERVISION_RATIO_VIOLATION,
    )
    assert err["error_id"] == "ERR_SUPERVISION_RATIO_VIOLATION", "0 chaperones < 1"


def test_slot_capacity_error_when_ratio_passes(api):
    """PRD §3.6: "both capacity pools must pre-check — `confirmed_count` plus
    `member_count` within `capacity_total` (otherwise
    `ERR_SLOT_CAPACITY_EXCEEDED`) and `confirmed_youth_count` plus `minor_count`
    within `capacity_youth` (otherwise `ERR_YOUTH_CAPACITY_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/supervision_ratio_beats_slot_capacity_on_booking_create
    """
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=5, capacity_youth=5)
    leader = make_participating_volunteer()
    (c1,) = make_certified_chaperones(1)

    # Ratio satisfied (ceil(4/8) == 1 declared and certified); only the total
    # pool overflows (0 + 10 > 5) while the youth pool fits (0 + 4 <= 5).
    err = validate_error(
        _booking_attempt(api, slot["id"], leader, 10, 4, 1, [c1["id"]], "School Wide"),
        ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED,
    )
    assert err["error_id"] == "ERR_SLOT_CAPACITY_EXCEEDED"
