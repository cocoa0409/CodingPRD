"""Authorisation: role-exclusive writes, wide-open reads, data ownership and duties segregation."""

from test_helpers import NON_EXISTENT_UUID, api_client, validate_error, validate_paginated, validate_success
from test_helpers.factories import (
    create_class_entry_payload,
    create_entry_payload,
    create_footing_maintenance_payload,
    create_official_assignment_payload,
    create_results_payload,
    create_ring_payload,
    create_ring_slot_payload,
    create_show_payload,
    placing_row,
)
from test_helpers.fixtures import (
    accept_entry,
    book_slot,
    build_active_coverage,
    build_approved_show,
    build_confirmed_entry,
    build_entry,
    class_version,
    create_coverage_shift,
    create_horse,
    create_official,
    create_rider,
    get_class,
    get_class_entry,
    get_entry,
    get_official,
    get_show,
    get_slot,
    invoice_entry,
    ring_version,
    start_slot,
    verify_entry,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_exhibitor_headers,
    make_judge_headers,
    make_steward_headers,
)

SECRETARY = TEST_USERS["show_secretary_headers"]
OFFICER = TEST_USERS["federation_officer_headers"]
RING_MASTER = TEST_USERS["ring_master_headers"]
GROUNDS = TEST_USERS["grounds_manager_headers"]
NO_HEADERS: dict = {}


def test_role_exclusive_writes_refuse_every_other_role_before_they_look_at_anything_else():
    """Eleven writes, each owned by exactly one role, are attempted by a role that does not own
    them — including the split approval chain, where the office submits the prize list and only the
    federation may decide it, and the licensed judge who still may not open a compliance case. The
    ordering probes matter as much as the refusals: a wrong-role write against a show id that does
    not exist reports the role failure rather than the missing show, and a request with no identity
    headers at all is unauthenticated even on the otherwise-shared read. The same read with headers
    succeeds, and the show's version is untouched by the whole sweep.

    PRD §2.2: "If either header is absent, or if `X-User-Role` is not one of the seven role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.2: "If both headers are present and well-formed but the named role is not among the roles authorised for the requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.12: "1. Header presence and role recognition — `ERR_UNAUTHENTICATED`."
    PRD §2.12: "2. Role authorisation for the endpoint — `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.12: "3. Existence of every path-segment resource, left to right — the per-type 404 codes of §2.8."

    Design: Corner/rbac/other_roles_rejected_on_exclusive_operations
    """
    ctx = build_approved_show(ring_specs=[{}])
    show_id, ring_id, class_id = ctx["show_id"], ctx["ring_id"], ctx["class_id"]
    rider = create_rider()
    horse = create_horse()
    official = create_official(license_roles=["JUDGE", "STEWARD"])
    row = build_entry(show_id, rider["id"], horse["id"], [class_id])
    shift = create_coverage_shift(show_id)
    before_version = get_show(show_id)["version"]

    validate_error(
        api_client.create_show(
            create_show_payload(name="Pirate Show", federation_show_id="FED-9999"), OFFICER
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.decide_show_license(show_id, {"decision": "APPROVE"}, SECRETARY),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_official(
            {
                "federation_official_id": "OF-9099",
                "full_name": "Rogue Official",
                "license_roles": ["JUDGE"],
                "license_level": 2,
                "licensed_disciplines": ["JUMPER"],
                "license_expires_on": "2027-12-31T00:00:00Z",
            },
            SECRETARY,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_ring_slot(
            create_ring_slot_payload(
                ring_id, class_id, "2026-09-10T14:00:00Z", ring_version(ring_id)
            ),
            SECRETARY,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.record_class_results(
            class_id, create_results_payload([], 20), SECRETARY
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_compliance_case(
            row["entry_id"],
            {
                "opened_by_official_id": official["id"],
                "case_type": "WELFARE_CITATION",
                "welfare_rule_code": "WR-12",
            },
            make_judge_headers(official["id"]),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_entry(
            show_id, create_entry_payload(rider["id"], horse["id"]), SECRETARY
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.record_footing_maintenance(
            ring_id, create_footing_maintenance_payload(), RING_MASTER
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.activate_coverage_shift(shift["id"], SECRETARY),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_point_submission(
            class_id, {"expected_class_version": class_version(class_id)}, GROUNDS
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    validate_error(
        api_client.create_ring(
            NON_EXISTENT_UUID, create_ring_payload(name="Ghost Ring"), GROUNDS
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    validate_error(
        api_client.create_show(
            create_show_payload(name="Anonymous Show", federation_show_id="FED-9998"), NO_HEADERS
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api_client.get_show(show_id, NO_HEADERS), "ERR_UNAUTHENTICATED", 401
    )

    after = validate_success(api_client.get_show(show_id, SECRETARY))
    assert after["version"] == before_version


def test_reads_are_open_to_all_seven_roles_and_are_never_scoped_by_the_caller():
    """Every role's shared operations are the reads, so the same show read seven times under seven
    different roles returns the same payload — no role sees a narrowed or redacted view. The point
    is sharpened on the reads a naive implementation would scope: grounds staff can list the
    entries of a show they do not own, a steward can read a class entry belonging to somebody
    else's rider, a ring master can pull a rider's standings, and the projection read is open to
    grounds staff, answering zero minutes while nothing is booked.

    PRD §2.2: "Every request to the API — reads included — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role the caller is acting in."
    PRD §2.2: "- When `X-User-Role` is `Exhibitor`, `X-User-ID` is the `id` of the acting `Rider`; ownership checks on any resource that references a `Rider` compare the resource's rider foreign-key field to `X-User-ID`."
    PRD §2.2: "- For those three entity-backed roles, `X-User-ID` must resolve to an existing row of the backing entity — an existing `Rider` for `Exhibitor`, an existing `Official` for `Judge` and `Steward`."
    PRD §3.6: "The read computes and stores nothing."
    PRD §2.4: "Filters are exact-match on the named field and may be combined; supplying none returns the whole collection."

    Design: Corner/rbac/shared_get_endpoints_open_to_every_role
    """
    ctx = build_approved_show(ring_specs=[{}])
    show_id, class_id = ctx["show_id"], ctx["class_id"]
    rider = create_rider()
    horse = create_horse()
    official = create_official(license_roles=["JUDGE", "STEWARD"])
    row = build_entry(show_id, rider["id"], horse["id"], [class_id])

    readers = [
        SECRETARY,
        OFFICER,
        RING_MASTER,
        GROUNDS,
        make_judge_headers(official["id"]),
        make_steward_headers(official["id"]),
        make_exhibitor_headers(rider["id"]),
    ]
    views = [validate_success(api_client.get_show(show_id, headers)) for headers in readers]
    assert len(views) == 7
    for view in views[1:]:
        assert view == views[0]

    _classes, class_meta = validate_paginated(
        api_client.list_classes(
            make_exhibitor_headers(rider["id"]),
            params={"division_id": ctx["division_id"], "status": "OPEN"},
        )
    )
    assert class_meta["total_count"] == 1

    _entries, entry_meta = validate_paginated(
        api_client.list_entries(GROUNDS, params={"show_id": show_id})
    )
    assert entry_meta["total_count"] == 1

    seen = validate_success(
        api_client.get_class_entry(row["class_entry_id"], make_steward_headers(official["id"]))
    )
    assert seen["id"] == row["class_entry_id"]

    standings = validate_success(
        api_client.get_rider_standings(rider["id"], RING_MASTER, params={"show_id": show_id})
    )
    assert standings["rider_id"] == rider["id"]
    assert standings["national_points_total"] == 0.0
    assert standings["regional_points_total"] == 0
    assert standings["regional_capped"] is False

    projection = validate_success(api_client.get_schedule_projection(show_id, GROUNDS))
    assert projection["projected_total_minutes"] == 0
    assert projection["class_projections"] == []


def test_ownership_of_an_entry_is_data_and_the_identity_ladder_is_checked_before_it():
    """Holding the Exhibitor role is not enough: the four ownership-checked writes are all refused
    for a perfectly valid second rider acting on the first rider's entry, including the creation
    call whose body merely names somebody else's rider. An acting id that resolves to no rider at
    all is refused earlier, as an unrecognised actor rather than as a non-owner. The owner's
    identical payment then succeeds, which proves the refusals were about identity and not about
    the request, and the entry was written exactly once.

    PRD §2.2: "Concretely, an `Exhibitor` acting on an entry must be the entry's `rider_id`, and a mismatch is `ERR_ENTRY_NOT_OWNED` (HTTP 403)."
    PRD §2.2: "When it does not, the request fails with `ERR_ACTOR_NOT_RECOGNIZED` (HTTP 403)."
    PRD §2.12: "4. Resolution of `X-User-ID` for the entity-backed roles — `ERR_ACTOR_NOT_RECOGNIZED`."
    PRD §2.12: "7. `Exhibitor` ownership of the entry being acted on — `ERR_ENTRY_NOT_OWNED`."
    PRD §3.5: "The acting exhibitor must be the entering rider — the submitted `rider_id` and the ownership check both resolve against `X-User-ID`, and a mismatch is `ERR_ENTRY_NOT_OWNED`."
    PRD §3.5: "A class entry starts life `ENTERED` and only reaches `CONFIRMED` when *both* entry dimensions have landed: `verification_status` of `ACCEPTED` and `settlement_status` of `PAID`."

    Design: Corner/rbac/foreign_entry_writes_rejected_for_non_owner
    """
    ctx = build_approved_show()
    class_id = ctx["class_id"]
    rider_a, rider_b = create_rider(), create_rider()
    horse_a, horse_b = create_horse(), create_horse()
    headers_a = make_exhibitor_headers(rider_a["id"])
    headers_b = make_exhibitor_headers(rider_b["id"])

    row_a = build_entry(ctx["show_id"], rider_a["id"], horse_a["id"], [class_id])
    build_entry(ctx["show_id"], rider_b["id"], horse_b["id"])
    verify_entry(row_a["entry_id"])
    accept_entry(row_a["entry_id"])
    invoiced = invoice_entry(row_a["entry_id"])
    assert invoiced["total_due_cents"] == 30000

    validate_error(
        api_client.pay_entry(row_a["entry_id"], {"amount_cents": 30000}, headers_b),
        "ERR_ENTRY_NOT_OWNED",
        403,
    )
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(row_a["entry_id"], class_id), headers_b
        ),
        "ERR_ENTRY_NOT_OWNED",
        403,
    )
    validate_error(
        api_client.withdraw_entry(row_a["entry_id"], headers_b), "ERR_ENTRY_NOT_OWNED", 403
    )
    validate_error(
        api_client.create_entry(
            ctx["show_id"], create_entry_payload(rider_a["id"], horse_a["id"]), headers_b
        ),
        "ERR_ENTRY_NOT_OWNED",
        403,
    )

    validate_error(
        api_client.pay_entry(
            row_a["entry_id"],
            {"amount_cents": 30000},
            make_exhibitor_headers(NON_EXISTENT_UUID),
        ),
        "ERR_ACTOR_NOT_RECOGNIZED",
        403,
    )

    paid = validate_success(
        api_client.pay_entry(row_a["entry_id"], {"amount_cents": 30000}, headers_a)
    )
    assert paid["settlement_status"] == "PAID"

    settled = get_entry(row_a["entry_id"])
    assert settled["verification_status"] == "ACCEPTED"
    assert settled["refunded_cents"] == 0
    assert get_class_entry(row_a["class_entry_id"])["status"] == "CONFIRMED"


def test_the_double_hatted_official_is_carded_but_may_not_sign_the_card():
    """Two chairs on one occupancy are legal to card — the official is already standing in that
    ring, so the time geometry exempts the second chair, and the load ledger charges the same
    fifty-three minutes twice. The clash surfaces later: the official holding both chairs cannot
    sign the card, an official holding no chair at all is refused earlier still as unassigned, and
    the single-hatted judge signs it. Neither refusal advanced anything, so the class records the
    winner's time exactly once.

    PRD §3.6: "The candidate is compared only against other `ACTIVE` assignments of the same official that sit on a *different* occupancy; a second chair on the very same occupancy is exempt from this check, because the official is already standing in that ring, and the duties clash it creates is caught instead by the segregation-of-duties rule at card time."
    PRD §3.6: "A new assignment has `status` of `ACTIVE`, and the official's `assigned_minutes` is increased by the whole minutes from the occupancy's `warmup_start_utc` to its `end_utc`; the official's `version` increments."
    PRD §3.7: "The acting judge, resolved from `X-User-ID`, must hold an assignment with `status` of `ACTIVE` and `official_role` of `JUDGE` on this class's `RUNNING` occupancy; if not, `ERR_JUDGE_NOT_ASSIGNED`."
    PRD §3.7: "Segregation of duties then forbids the same person from also holding an `ACTIVE` assignment with `official_role` of `STEWARD` on that same occupancy; if they do, the card is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "For each chair the matrix demands in a positive quantity, the occupancy must carry at least that many *distinct* officials holding an `ACTIVE` assignment in that chair; chairs the matrix sets to zero are not checked at all."
    PRD §3.7: "The class moves `IN_PROGRESS → JUDGED` with `actual_minutes` written from the card and `placed_count` recomputed as the number of its class entries that have a non-null `placing` and a `status` of `COMPLETED`."

    Design: Corner/rbac/same_official_cannot_judge_and_steward_one_slot
    """
    ctx = build_approved_show(ring_specs=[{}])
    rider = create_rider()
    horse = create_horse()
    row = build_confirmed_entry(ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]])

    slot = book_slot(ctx["ring_id"], ctx["class_id"], "2026-09-10T14:00:00Z")
    assert slot["duration_minutes"] == 23
    assert slot["warmup_start_utc"] == "2026-09-10T13:30:00Z"

    off_x = create_official(license_roles=["JUDGE", "STEWARD"])
    off_y = create_official(license_roles=["JUDGE"])
    off_z = create_official(license_roles=["JUDGE"])

    for official_id, chair in ((off_x["id"], "JUDGE"), (off_x["id"], "STEWARD"), (off_y["id"], "JUDGE")):
        carded = validate_success(
            api_client.create_official_assignment(
                create_official_assignment_payload(official_id, slot["id"], chair), SECRETARY
            ),
            201,
        )
        assert carded["status"] == "ACTIVE"

    assert get_official(off_x["id"])["assigned_minutes"] == 106
    assert get_official(off_y["id"])["assigned_minutes"] == 53
    assert get_official(off_z["id"])["assigned_minutes"] == 0

    build_active_coverage(ctx["show_id"])
    assert start_slot(slot["id"])["status"] == "RUNNING"
    assert get_class(ctx["class_id"])["status"] == "IN_PROGRESS"

    card = create_results_payload([placing_row(row["class_entry_id"], 1, 61.5)], 23)
    validate_error(
        api_client.record_class_results(ctx["class_id"], card, make_judge_headers(off_x["id"])),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )
    validate_error(
        api_client.record_class_results(ctx["class_id"], card, make_judge_headers(off_z["id"])),
        "ERR_JUDGE_NOT_ASSIGNED",
        403,
    )

    judged = validate_success(
        api_client.record_class_results(ctx["class_id"], card, make_judge_headers(off_y["id"]))
    )
    assert judged["status"] == "JUDGED"
    assert judged["actual_minutes"] == 23
    assert judged["placed_count"] == 1

    winner = get_class_entry(row["class_entry_id"])
    assert winner["status"] == "COMPLETED"
    assert winner["placing"] == 1
    assert winner["round_seconds"] == 61.5
    assert get_slot(slot["id"])["status"] == "COMPLETED"
