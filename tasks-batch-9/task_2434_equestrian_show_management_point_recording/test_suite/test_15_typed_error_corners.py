"""Typed refusals: per-type 404s for body and path references, and the state guards behind them."""

from test_helpers import NON_EXISTENT_UUID, api_client, validate_error, validate_paginated, validate_success
from test_helpers.factories import (
    acknowledgement_payload,
    create_class_entry_payload,
    create_class_payload,
    create_compliance_case_payload,
    create_division_payload,
    create_entry_payload,
    create_official_assignment_payload,
    create_results_payload,
    create_ring_slot_payload,
    placing_row,
)
from test_helpers.fixtures import (
    accept_entry,
    book_slot,
    build_approved_show,
    build_show_with_class_list,
    class_version,
    create_horse,
    create_official,
    create_rider,
    create_show,
    get_class,
    get_entry,
    get_ring,
    get_show,
    invoice_entry,
    open_class,
    ring_version,
    set_clock,
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


def test_every_reference_that_resolves_to_nothing_gets_its_own_typed_404():
    """Fourteen probes, each substituting one well-formed but unknown identifier into one request
    and expecting the code that names that type — body references and path segments alike. Two of
    them pin the ladder rather than the catalogue: a bogus ring reference reports the missing ring
    even though the same body carries a version that could have been called stale, and a bogus card
    row reports the missing class entry even though the class is not in progress. The control call
    on real ids reaches its state guard, so the fourteen 404s came from reference resolution and
    not from blanket rejection, and nothing in the sweep wrote a row.

    PRD §2.8: "The same catalogue serves references supplied inside a request body rather than in the path."
    PRD §2.8: "Every foreign key in a payload must resolve to an existing row before any business rule is consulted, and the code names the missing type: a `show_id` that resolves to nothing is `ERR_SHOW_NOT_FOUND`, a `ring_id` is `ERR_RING_NOT_FOUND`, a `class_id` or a `qualifier_for_class_id` is `ERR_CLASS_NOT_FOUND`, a `slot_id` is `ERR_SLOT_NOT_FOUND`, an `entry_id` is `ERR_ENTRY_NOT_FOUND`, an `official_id` or an `opened_by_official_id` is `ERR_OFFICIAL_NOT_FOUND`, a `rider_id` is `ERR_RIDER_NOT_FOUND`, a `horse_id` is `ERR_HORSE_NOT_FOUND`, and a `class_entry_id` named inside a judge's card is `ERR_CLASS_ENTRY_NOT_FOUND`."
    PRD §2.8: "The not-found codes are per resource type: `ERR_SHOW_NOT_FOUND`, `ERR_RING_NOT_FOUND`, `ERR_DIVISION_NOT_FOUND`, `ERR_CLASS_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_CLASS_ENTRY_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_POINT_SUBMISSION_NOT_FOUND`, `ERR_COMPLIANCE_CASE_NOT_FOUND` and `ERR_COVERAGE_SHIFT_NOT_FOUND`."
    PRD §2.12: "5. Existence of every foreign key supplied in the request body — the per-type 404 codes of §2.8."
    PRD §2.12: "8. The optimistic-concurrency version match of §2.7 — `ERR_STALE_VERSION`."
    PRD §2.12: "9. The target resource's own state precondition — the 409 state codes."
    PRD §2.12: "When more than one rule would reject a request, the earlier rule in the following ladder wins, and its error is the one returned."

    Design: Corner/errors/body_and_path_fk_ids_return_typed_not_found
    """
    ctx = build_approved_show(ring_specs=[{}])
    ring_id, class_id = ctx["ring_id"], ctx["class_id"]
    rider = create_rider()
    horse = create_horse()
    official = create_official(license_roles=["JUDGE", "STEWARD"])
    exhibitor = make_exhibitor_headers(rider["id"])
    entry = validate_success(
        api_client.create_entry(
            ctx["show_id"], create_entry_payload(rider["id"], horse["id"]), exhibitor
        ),
        201,
    )

    validate_error(
        api_client.create_ring_slot(
            create_ring_slot_payload(
                NON_EXISTENT_UUID, class_id, "2026-09-10T14:00:00Z", ring_version(ring_id)
            ),
            RING_MASTER,
        ),
        "ERR_RING_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_ring_slot(
            create_ring_slot_payload(
                ring_id, NON_EXISTENT_UUID, "2026-09-10T14:00:00Z", ring_version(ring_id)
            ),
            RING_MASTER,
        ),
        "ERR_CLASS_NOT_FOUND",
        404,
    )

    slot = book_slot(ring_id, class_id, "2026-09-10T14:00:00Z")

    validate_error(
        api_client.create_official_assignment(
            create_official_assignment_payload(NON_EXISTENT_UUID, slot["id"]), SECRETARY
        ),
        "ERR_OFFICIAL_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_official_assignment(
            create_official_assignment_payload(official["id"], NON_EXISTENT_UUID), SECRETARY
        ),
        "ERR_SLOT_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_entry(
            ctx["show_id"], create_entry_payload(NON_EXISTENT_UUID, horse["id"]), exhibitor
        ),
        "ERR_RIDER_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_entry(
            ctx["show_id"], create_entry_payload(rider["id"], NON_EXISTENT_UUID), exhibitor
        ),
        "ERR_HORSE_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(NON_EXISTENT_UUID, class_id), exhibitor
        ),
        "ERR_ENTRY_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(entry["id"], NON_EXISTENT_UUID), exhibitor
        ),
        "ERR_CLASS_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_compliance_case(
            entry["id"],
            create_compliance_case_payload(NON_EXISTENT_UUID, sample_code="SMP-4001"),
            make_steward_headers(official["id"]),
        ),
        "ERR_OFFICIAL_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.record_class_results(
            class_id,
            create_results_payload([placing_row(NON_EXISTENT_UUID, 1, 60.0)], 20),
            make_judge_headers(official["id"]),
        ),
        "ERR_CLASS_ENTRY_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_class(
            NON_EXISTENT_UUID, create_class_payload(class_number=199, name="Orphan Class"), SECRETARY
        ),
        "ERR_DIVISION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.acknowledge_point_submission(
            NON_EXISTENT_UUID,
            acknowledgement_payload("NATIONAL", "ACCEPTED", body_reference="NAT-REF-1"),
            OFFICER,
        ),
        "ERR_POINT_SUBMISSION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.record_case_finding(NON_EXISTENT_UUID, {"finding": "NEGATIVE"}, OFFICER),
        "ERR_COMPLIANCE_CASE_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.activate_coverage_shift(NON_EXISTENT_UUID, GROUNDS),
        "ERR_COVERAGE_SHIFT_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_rider_standings(NON_EXISTENT_UUID, SECRETARY), "ERR_RIDER_NOT_FOUND", 404
    )
    validate_error(
        api_client.get_official_assignment(NON_EXISTENT_UUID, SECRETARY),
        "ERR_ASSIGNMENT_NOT_FOUND",
        404,
    )

    validate_error(
        api_client.create_point_submission(
            class_id, {"expected_class_version": class_version(class_id)}, SECRETARY
        ),
        "ERR_CLASS_RESULTS_NOT_POSTED",
        409,
    )

    slots, slot_meta = validate_paginated(
        api_client.list_ring_slots(RING_MASTER, params={"ring_id": ring_id})
    )
    assert slot_meta["total_count"] == 1
    assert slots[0]["id"] == slot["id"]
    assert get_class(class_id)["status"] == "SCHEDULED"

    _rows, entry_meta = validate_paginated(
        api_client.list_entries(SECRETARY, params={"show_id": ctx["show_id"]})
    )
    assert entry_meta["total_count"] == 1
    _cards, card_meta = validate_paginated(
        api_client.list_official_assignments(SECRETARY, params={"slot_id": slot["id"]})
    )
    assert card_meta["total_count"] == 0


def test_the_prize_list_refuses_the_four_construction_errors_on_their_exact_boundaries():
    """Building the prize list is boundary work: a fence height one centimetre outside the
    division's band is refused at both ends while heights exactly on the floor and the ceiling are
    accepted, since the band is inclusive. A class number already used elsewhere in the same show
    collides even when the new class hangs under a different division, so uniqueness is show-scoped.
    A division share that would take the show to 10001 basis points is refused and the one that
    lands it on exactly 10000 is accepted. And a show with no divisions at all cannot submit its
    prize list. None of the four refusals left a row behind.

    PRD §3.1: "The fence height must lie inside the division's band, inclusive at both ends: a height equal to `min_jump_height_cm` or equal to `max_jump_height_cm` is acceptable, anything below the former or above the latter is `ERR_JUMP_HEIGHT_OUT_OF_RANGE`."
    PRD §3.1: "Creating one requires a `class_number` — the prize-list number, at least 1, and unique across every class of the same show, with a collision reported as `ERR_CLASS_NUMBER_DUPLICATE` — a printed `name`, a `jump_height_cm`, a per-horse `entry_fee_cents`, a `class_share_bp` between 0 and 10000 inclusive claiming a slice of the division's allotment, and a `max_entries` ceiling of at least 1."
    PRD §3.1: "If adding the division would push the show's `ACTIVE` divisions' shares above 10000 basis points in total, the creation is refused with `ERR_DIVISION_SHARE_OVERSUBSCRIBED`."
    PRD §3.1: "A new division is created with `status` of `ACTIVE` and `division_allotment_cents` of 0, and the show's `division_share_bp_total` and `version` are both recomputed on creation."
    PRD §3.1: "Submission from either origin requires the prize list to be substantive: the show must have at least one `CompetitionDivision` whose `status` is `ACTIVE` and at least one class beneath its divisions, or the submission fails with `ERR_CLASS_LIST_INCOMPLETE`."

    Design: Corner/errors/class_list_construction_errors_rejected
    """
    ctx = build_show_with_class_list()
    show_id, div_j = ctx["show_id"], ctx["division_id"]

    validate_error(
        api_client.create_class(
            div_j,
            create_class_payload(class_number=104, name="Too High", jump_height_cm=131),
            SECRETARY,
        ),
        "ERR_JUMP_HEIGHT_OUT_OF_RANGE",
        422,
    )
    validate_error(
        api_client.create_class(
            div_j,
            create_class_payload(class_number=105, name="Too Low", jump_height_cm=99),
            SECRETARY,
        ),
        "ERR_JUMP_HEIGHT_OUT_OF_RANGE",
        422,
    )
    on_the_floor = validate_success(
        api_client.create_class(
            div_j,
            create_class_payload(
                class_number=106, name="On The Floor", jump_height_cm=100, class_share_bp=1000
            ),
            SECRETARY,
        ),
        201,
    )
    on_the_ceiling = validate_success(
        api_client.create_class(
            div_j,
            create_class_payload(
                class_number=107, name="On The Ceiling", jump_height_cm=130, class_share_bp=1000
            ),
            SECRETARY,
        ),
        201,
    )
    assert on_the_floor["jump_height_cm"] == 100
    assert on_the_ceiling["jump_height_cm"] == 130

    validate_error(
        api_client.create_division(
            show_id,
            create_division_payload(
                name="Oversubscribed",
                discipline="HUNTER",
                min_jump_height_cm=80,
                max_jump_height_cm=110,
                division_share_bp=6668,
                jumpoff_enabled=False,
            ),
            SECRETARY,
        ),
        "ERR_DIVISION_SHARE_OVERSUBSCRIBED",
        422,
    )
    div_h = validate_success(
        api_client.create_division(
            show_id,
            create_division_payload(
                name="Exact Fit",
                discipline="HUNTER",
                min_jump_height_cm=80,
                max_jump_height_cm=110,
                division_share_bp=6667,
                jumpoff_enabled=False,
            ),
            SECRETARY,
        ),
        201,
    )
    assert div_h["status"] == "ACTIVE"
    assert get_show(show_id)["division_share_bp_total"] == 10000

    validate_error(
        api_client.create_class(
            div_h["id"],
            create_class_payload(
                class_number=101, name="Duplicate Number", jump_height_cm=100, class_share_bp=1000
            ),
            SECRETARY,
        ),
        "ERR_CLASS_NUMBER_DUPLICATE",
        409,
    )

    empty_show = create_show(
        name="Empty Show",
        federation_show_id="FED-2435",
        start_utc="2026-10-10T13:00:00Z",
        end_utc="2026-10-11T22:00:00Z",
        entry_close_utc="2026-10-01T00:00:00Z",
        prize_money_pool_cents=50000,
        stall_capacity=10,
    )
    validate_error(
        api_client.submit_show_license(empty_show["id"], SECRETARY),
        "ERR_CLASS_LIST_INCOMPLETE",
        422,
    )
    assert get_show(empty_show["id"])["license_status"] == "DRAFT"
    assert get_show(show_id)["license_status"] == "DRAFT"

    _under_j, meta_j = validate_paginated(
        api_client.list_classes(SECRETARY, params={"division_id": div_j})
    )
    assert meta_j["total_count"] == 3
    _under_h, meta_h = validate_paginated(
        api_client.list_classes(SECRETARY, params={"division_id": div_h["id"]})
    )
    assert meta_h["total_count"] == 0


def test_intake_refusals_fire_at_their_edges_and_in_their_declared_internal_order():
    """A class whose ceiling is one entry is full the moment that entry lands, and the next rider
    is refused. Repeating a pairing on a class that is not full reports the duplicate, but
    repeating the same pairing on the full class reports fullness instead, which is the declared
    order inside the capacity band. A payment one cent short and a payment one cent over are both
    refused and leave the entry invoiced; the exact figure settles it. And the entry window is a
    strictly-before comparison, so the instant equal to the closing time is already shut for both
    the entry and the class-entry endpoint.

    PRD §3.5: "The class's `entry_count` must be strictly less than its `max_entries`; a full class is `ERR_CLASS_FULL`."
    PRD §3.5: "And no existing class entry may already pair the same entry with the same class with a `status` of `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED` — a duplicate is `ERR_DUPLICATE_CLASS_ENTRY`, while a previously `SCRATCHED` pairing does not block a fresh one."
    PRD §2.12: "14. Capacity and shape constraints (jump-height band, class-number uniqueness, division share, class fullness, duplicate class entry, official load ceiling, entries present to judge, placings validity, point eligibility, class-list completeness, coverage check-in lead, finding applicability)."
    PRD §3.5: "An entry not in `INVOICED` is refused with `ERR_ENTRY_NOT_INVOICED`, and an `amount_cents` that is not exactly equal to `total_due_cents` — short or over — is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.5: "And the logical clock must be strictly before the show's `entry_close_utc`; at or after that instant the answer is `ERR_ENTRY_WINDOW_CLOSED`."
    PRD §3.5: "The logical clock must still be strictly before the show's `entry_close_utc`, otherwise `ERR_ENTRY_WINDOW_CLOSED`."

    Design: Corner/errors/entry_intake_errors_rejected
    """
    ctx = build_approved_show(
        class_specs=[
            {"class_number": 101, "name": "Open Jumper 1.20m", "max_entries": 1},
            {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110,
             "class_share_bp": 1000, "max_entries": 30},
        ]
    )
    class_101, class_102 = ctx["class_ids"]

    rider_a, rider_b = create_rider(), create_rider()
    horse_a, horse_b = create_horse(), create_horse()
    headers_a = make_exhibitor_headers(rider_a["id"])
    headers_b = make_exhibitor_headers(rider_b["id"])
    entry_a = validate_success(
        api_client.create_entry(
            ctx["show_id"], create_entry_payload(rider_a["id"], horse_a["id"]), headers_a
        ),
        201,
    )
    entry_b = validate_success(
        api_client.create_entry(
            ctx["show_id"], create_entry_payload(rider_b["id"], horse_b["id"]), headers_b
        ),
        201,
    )

    validate_success(
        api_client.create_class_entry(
            create_class_entry_payload(entry_a["id"], class_101), headers_a
        ),
        201,
    )
    assert get_class(class_101)["entry_count"] == 1
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(entry_b["id"], class_101), headers_b
        ),
        "ERR_CLASS_FULL",
        409,
    )

    validate_success(
        api_client.create_class_entry(
            create_class_entry_payload(entry_a["id"], class_102), headers_a
        ),
        201,
    )
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(entry_a["id"], class_102), headers_a
        ),
        "ERR_DUPLICATE_CLASS_ENTRY",
        409,
    )
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(entry_a["id"], class_101), headers_a
        ),
        "ERR_CLASS_FULL",
        409,
    )

    verify_entry(entry_a["id"])
    accept_entry(entry_a["id"])
    invoiced = invoice_entry(entry_a["id"])
    assert invoiced["preliminary_subtotal_cents"] == 50000
    assert invoiced["office_fee_cents"] == 2500
    assert invoiced["total_due_cents"] == 52500

    validate_error(
        api_client.pay_entry(entry_a["id"], {"amount_cents": 52499}, headers_a),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
        422,
    )
    validate_error(
        api_client.pay_entry(entry_a["id"], {"amount_cents": 52501}, headers_a),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
        422,
    )
    assert get_entry(entry_a["id"])["settlement_status"] == "INVOICED"

    settled = validate_success(
        api_client.pay_entry(entry_a["id"], {"amount_cents": 52500}, headers_a)
    )
    assert settled["settlement_status"] == "PAID"

    set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api_client.create_entry(
            ctx["show_id"], create_entry_payload(rider_b["id"], horse_b["id"]), headers_b
        ),
        "ERR_ENTRY_WINDOW_CLOSED",
        409,
    )
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(entry_b["id"], class_102), headers_b
        ),
        "ERR_ENTRY_WINDOW_CLOSED",
        409,
    )

    assert get_class(class_101)["entry_count"] == 1
    _rows, meta = validate_paginated(
        api_client.list_class_entries(SECRETARY, params={"class_id": class_102})
    )
    assert meta["total_count"] == 1


def test_the_scheduling_and_results_path_reports_each_state_guard_it_trips():
    """One show exercises every state guard on the way from prize list to standings. A class still
    PLANNED cannot be booked; a class already holding an occupancy cannot be booked again even at a
    time hours clear of the first, so it is the scheduling guard and not the overlap geometry that
    refuses it; an already-open class cannot be re-opened. The show window is inclusive at the far
    end, so an occupancy ending ten minutes past the closing instant is refused while one ending
    exactly on it is accepted. Posting a class that no judge has carded is refused, and raising a
    standings submission against a fresh version still fails on the class's state, since the
    concurrency check passes and the state guard is what remains.

    PRD §3.6: "Only a class in `OPEN` may be booked, otherwise `ERR_CLASS_NOT_OPEN`; and a class that already holds an occupancy on any ring with `status` of `SCHEDULED`, `RUNNING` or `COMPLETED` may not be booked a second time, which is `ERR_CLASS_ALREADY_SCHEDULED`."
    PRD §3.6: "The booked window must be fully contained inside the show's competition window: the show's `start_utc` must be at or before the occupancy's `start_utc`, and the occupancy's `end_utc` must be at or before the show's `end_utc`."
    PRD §3.6: "Anything else is `ERR_SLOT_OUTSIDE_SHOW_WINDOW`."
    PRD §3.1: "Only a class in `PLANNED` may be opened — otherwise `ERR_CLASS_NOT_PLANNED` — the owning show's licence must be `APPROVED`, and the owning division's `status` must be `ACTIVE`."
    PRD §3.8: "A class not in `JUDGED` is refused with `ERR_CLASS_NOT_JUDGED`."
    PRD §3.8: "A class not in `RESULTS_POSTED` is refused with `ERR_CLASS_RESULTS_NOT_POSTED`, and a class whose `point_eligible` is false — that is, whose `confirmed_entry_count` is below 3 — is refused with `ERR_CLASS_NOT_POINT_ELIGIBLE`."
    PRD §3.6: "The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count."

    Design: Corner/errors/scheduling_state_errors_rejected
    """
    ctx = build_approved_show(
        class_specs=[
            {"class_number": 101, "name": "Class 101"},
            {"class_number": 102, "name": "Class 102", "class_share_bp": 1000},
            {"class_number": 103, "name": "Class 103", "class_share_bp": 1000},
        ],
        ring_specs=[{}],
        open_classes=False,
    )
    ring_id = ctx["ring_id"]
    class_101, class_102, class_103 = ctx["class_ids"]
    open_class(class_101)
    open_class(class_103)

    def book(class_id, start_utc):
        return api_client.create_ring_slot(
            create_ring_slot_payload(ring_id, class_id, start_utc, ring_version(ring_id)),
            RING_MASTER,
        )

    validate_error(book(class_102, "2026-09-10T14:00:00Z"), "ERR_CLASS_NOT_OPEN", 409)

    slot_101 = validate_success(book(class_101, "2026-09-10T14:00:00Z"), 201)
    assert slot_101["duration_minutes"] == 20
    assert get_class(class_101)["status"] == "SCHEDULED"

    validate_error(book(class_101, "2026-09-10T16:00:00Z"), "ERR_CLASS_ALREADY_SCHEDULED", 409)
    validate_error(api_client.open_class(class_101, SECRETARY), "ERR_CLASS_NOT_PLANNED", 409)

    validate_error(
        book(class_103, "2026-09-13T21:50:00Z"), "ERR_SLOT_OUTSIDE_SHOW_WINDOW", 409
    )
    slot_103 = validate_success(book(class_103, "2026-09-13T21:40:00Z"), 201)
    assert slot_103["end_utc"] == "2026-09-13T22:00:00Z"

    validate_error(
        api_client.post_class_results(class_101, SECRETARY), "ERR_CLASS_NOT_JUDGED", 409
    )
    validate_error(
        api_client.create_point_submission(
            class_101, {"expected_class_version": class_version(class_101)}, SECRETARY
        ),
        "ERR_CLASS_RESULTS_NOT_POSTED",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_ring_slots(
            RING_MASTER, params={"ring_id": ring_id, "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {slot_101["id"], slot_103["id"]}

    ring = get_ring(ring_id)
    assert ring["scheduled_minutes_total"] == 40
    assert ring["slot_count"] == 2
    assert ring["version"] == 3
