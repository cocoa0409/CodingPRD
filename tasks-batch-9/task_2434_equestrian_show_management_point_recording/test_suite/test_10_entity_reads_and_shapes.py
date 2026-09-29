"""Entity shapes: creation baselines, derived fields, declared defaults and the read paths."""

from test_helpers import api_client, validate_error, validate_paginated, validate_success
from test_helpers.assertions import (
    assert_class,
    assert_class_entry,
    assert_entry,
    assert_horse,
    assert_point_submission,
    assert_ring,
    assert_show,
    assert_stall_ledger_invariant,
)
from test_helpers.constants import MISSING_UUID, TEST_DEFAULTS
from test_helpers.factories import (
    create_class_payload,
    create_division_payload,
    create_entry_payload,
    create_horse_payload,
    create_official_payload,
    create_show_payload,
)
from test_helpers.fixtures import (
    approve_license,
    build_point_submission,
    create_class,
    create_division,
    create_horse,
    create_rider,
    create_show,
    get_class,
    get_show,
    open_class,
)
from test_helpers.test_users import (
    SHOW_SECRETARY_USER_ID,
    TEST_USERS,
    make_exhibitor_headers,
)

SECRETARY = TEST_USERS["show_secretary_headers"]
OFFICER = TEST_USERS["federation_officer_headers"]
RING_MASTER = TEST_USERS["ring_master_headers"]
GROUNDS = TEST_USERS["grounds_manager_headers"]
STEWARD = TEST_USERS["steward_headers"]

PLAIN_JUMPER_CLASSES = [
    {"class_number": 101, "name": "Open Jumper 1.20m", "jump_height_cm": 120, "class_share_bp": 1669},
    {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110, "class_share_bp": 1000},
    {"class_number": 103, "name": "Open Jumper 1.00m", "jump_height_cm": 100, "class_share_bp": 1000},
]


def _two_divisions_and_five_classes():
    """A JUMPER division of four classes — one of them a qualifier — and a HUNTER division of one."""
    show = create_show()
    division_j = create_division(show["id"])
    classes = [create_class(division_j["id"], **spec) for spec in PLAIN_JUMPER_CLASSES]
    qualifier = create_class(
        division_j["id"],
        class_number=104,
        name="Jumper Classic 1.30m",
        jump_height_cm=130,
        class_share_bp=1000,
        qualifier_for_class_id=classes[0]["id"],
    )
    division_h = create_division(
        show["id"],
        name="Open Hunter",
        discipline="HUNTER",
        min_jump_height_cm=80,
        max_jump_height_cm=130,
        division_share_bp=3000,
    )
    hunter_class = create_class(
        division_h["id"], class_number=201, name="Open Hunter 1.20m", class_share_bp=1000
    )
    return {
        "show_id": show["id"],
        "division_j_id": division_j["id"],
        "division_h_id": division_h["id"],
        "class_ids": [row["id"] for row in classes],
        "qualifier_id": qualifier["id"],
        "hunter_class_id": hunter_class["id"],
    }


def test_a_new_show_seeds_both_conserved_ledgers_from_its_own_declared_figures():
    """Creation echoes all ten declared inputs and seeds all nine computed fields in the same
    breath: the unallocated purse starts at the whole 750000-cent pool and the available stalls at
    the whole capacity of 40, rather than sitting at zero until the first ledger write moves them.

    PRD §3.1: "A `ShowSecretary` creates it with the `name` that will be printed on the prize list, the `federation_show_id` applied for on the licence, the `venue` at which it will run, and the `competition_level` at which it is being held — one of `LOCAL`, `REGIONAL`, `NATIONAL` or `PREMIER`, a choice that later dictates both how many officials each class needs and how highly licensed those officials must be."
    PRD §3.1: "At creation the show's `license_status` is `DRAFT`, `revision_count` is 0, `allocated_prize_cents` is 0, `unallocated_prize_cents` equals `prize_money_pool_cents`, `reserved_stall_count` is 0, `available_stall_count` equals `stall_capacity`, `division_share_bp_total` is 0 and `welfare_strike_count` is 0."
    PRD §2.5: "Every persisted resource carries a server-minted `id`: a UUID with no type prefix, assigned at creation and never reused or rewritten."
    PRD §2.5: "Every resource in this system additionally carries `updated_at` — same format, rewritten on every mutation — and `version`, an integer that begins at 1 on creation and increments by exactly one each time the resource is mutated."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/show_creation_returns_full_fiscal_baseline
    """
    response = api_client.create_show(create_show_payload(), SECRETARY)
    created = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]

    assert created["name"] == "Autumn Classic"
    assert created["federation_show_id"] == "FED-2434"
    assert created["venue"] == "Ridgeline Park"
    assert created["competition_level"] == "LOCAL"
    assert created["start_utc"] == TEST_DEFAULTS["SHOW_START_UTC"]
    assert created["end_utc"] == TEST_DEFAULTS["SHOW_END_UTC"]
    assert created["entry_close_utc"] == TEST_DEFAULTS["ENTRY_CLOSE_UTC"]
    assert created["prize_money_pool_cents"] == 750000
    assert created["stall_capacity"] == 40
    assert created["stall_fee_cents"] == 7500

    assert_show(created)
    assert created["version"] == 1
    assert created["license_status"] == "DRAFT"
    assert created["revision_count"] == 0
    assert created["allocated_prize_cents"] == 0
    assert created["unallocated_prize_cents"] == 750000
    assert created["reserved_stall_count"] == 0
    assert created["available_stall_count"] == 40
    assert created["division_share_bp_total"] == 0
    assert created["welfare_strike_count"] == 0
    assert_stall_ledger_invariant(created)


def test_a_ring_with_no_occupancies_reads_back_its_declared_shape_with_zeroed_counters():
    """Every optional figure is supplied explicitly, so the read is a pure echo — including the
    88-point footing seed and the 15-minute turnover — and the two occupancy counters report 0
    rather than null on a ring nothing has been booked into yet.

    PRD §3.3: "A `ShowSecretary` adds one with a `name` such as "Grand Prix Field" and a `surface_type` of `SAND_FIBER`, `GRASS` or `CLAY`."
    PRD §3.3: "A new ring has `status` of `AVAILABLE`, `scheduled_minutes_total` of 0 and `slot_count` of 0, and its creation increments the parent show's `version`."
    PRD §3.3: "`AVAILABLE` and `MAINTENANCE_HOLD` are the only two ring postures, and neither is terminal."
    PRD §2.5: "Every resource in this system additionally carries `updated_at` — same format, rewritten on every mutation — and `version`, an integer that begins at 1 on creation and increments by exactly one each time the resource is mutated."

    Design: Corner/entities/ring_retrieval_matches_stored_row
    """
    show = create_show()
    created = validate_success(
        api_client.create_ring(
            show["id"],
            {
                "name": "Ring A",
                "surface_type": "SAND_FIBER",
                "footing_condition_score": 88,
                "turnover_buffer_minutes": 15,
                "warmup_capacity_horses": 9,
            },
            SECRETARY,
        ),
        201,
    )

    fetched = validate_success(api_client.get_ring(created["id"], GROUNDS))
    assert_ring(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["show_id"] == show["id"]
    assert fetched["name"] == "Ring A"
    assert fetched["surface_type"] == "SAND_FIBER"
    assert fetched["footing_condition_score"] == 88
    assert fetched["turnover_buffer_minutes"] == 15
    assert fetched["warmup_capacity_horses"] == 9
    assert fetched["status"] == "AVAILABLE"
    assert fetched["scheduled_minutes_total"] == 0
    assert fetched["slot_count"] == 0
    assert fetched["version"] == 1


def test_the_class_list_narrows_before_it_windows_and_walks_the_qualifier_edge():
    """Four of the show's five classes sit in the jumper division, so a two-row page reports a
    total of four and not five, and the page that exhausts the filtered set flips `has_more` to
    false. The self-referential filter returns only the class that names 101 as its championship,
    and an unwindowed read falls back to the declared page size.

    PRD §2.3: "`limit` defaults to 10, may be no smaller than 1 and no larger than 100."
    PRD §2.3: "Both are echoed in the `meta` block of the response alongside `total_count` — the number of rows matching the request's filters before the window is applied — and `has_more`, which is true when rows remain after the current window."
    PRD §2.3: "Filters supplied alongside pagination narrow the collection before the window is taken, so `total_count` reflects the filtered population and not the whole table."
    PRD §2.4: "The `qualifier_for_class_id` filter is how a caller discovers which classes feed a given championship class."

    Design: Corner/entities/class_listing_filters_and_paginates
    """
    ctx = _two_divisions_and_five_classes()

    page_one, meta_one = validate_paginated(
        api_client.list_classes(
            SECRETARY, params={"division_id": ctx["division_j_id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 4
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api_client.list_classes(
            SECRETARY, params={"division_id": ctx["division_j_id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page_two) == 2
    assert meta_two["total_count"] == 4
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False

    chain, chain_meta = validate_paginated(
        api_client.list_classes(SECRETARY, params={"qualifier_for_class_id": ctx["class_ids"][0]})
    )
    assert chain_meta["total_count"] == 1
    assert [row["id"] for row in chain] == [ctx["qualifier_id"]]

    everything, everything_meta = validate_paginated(
        api_client.list_classes(SECRETARY, params={"status": "PLANNED"})
    )
    assert everything_meta["total_count"] == 5
    assert len(everything) == 5
    assert everything_meta["limit"] == 10
    assert everything_meta["offset"] == 0
    assert everything_meta["has_more"] is False


def test_every_unresolvable_path_id_names_the_resource_type_it_addressed():
    """Eleven reads against an empty store, each answered by the code for the type actually
    addressed rather than a single shared not-found code, and each carrying the error envelope's
    two data fields.

    PRD §2.8: "Path segments are resolved strictly left to right, and the first segment that does not resolve determines the error."
    PRD §2.8: "The not-found codes are per resource type: `ERR_SHOW_NOT_FOUND`, `ERR_RING_NOT_FOUND`, `ERR_DIVISION_NOT_FOUND`, `ERR_CLASS_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_CLASS_ENTRY_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_POINT_SUBMISSION_NOT_FOUND`, `ERR_COMPLIANCE_CASE_NOT_FOUND` and `ERR_COVERAGE_SHIFT_NOT_FOUND`. All carry HTTP 404."
    PRD §2.8: "Every foreign key in a payload must resolve to an existing row before any business rule is consulted, and the code names the missing type: a `show_id` that resolves to nothing is `ERR_SHOW_NOT_FOUND`, a `ring_id` is `ERR_RING_NOT_FOUND`, a `class_id` or a `qualifier_for_class_id` is `ERR_CLASS_NOT_FOUND`, a `slot_id` is `ERR_SLOT_NOT_FOUND`, an `entry_id` is `ERR_ENTRY_NOT_FOUND`, an `official_id` or an `opened_by_official_id` is `ERR_OFFICIAL_NOT_FOUND`, a `rider_id` is `ERR_RIDER_NOT_FOUND`, a `horse_id` is `ERR_HORSE_NOT_FOUND`, and a `class_entry_id` named inside a judge's card is `ERR_CLASS_ENTRY_NOT_FOUND`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/unknown_path_ids_return_typed_not_found
    """
    probes = [
        (api_client.get_show(MISSING_UUID, SECRETARY), "ERR_SHOW_NOT_FOUND"),
        (api_client.get_ring(MISSING_UUID, RING_MASTER), "ERR_RING_NOT_FOUND"),
        (api_client.get_class(MISSING_UUID, SECRETARY), "ERR_CLASS_NOT_FOUND"),
        (api_client.get_ring_slot(MISSING_UUID, RING_MASTER), "ERR_SLOT_NOT_FOUND"),
        (api_client.get_official(MISSING_UUID, OFFICER), "ERR_OFFICIAL_NOT_FOUND"),
        (api_client.get_official_assignment(MISSING_UUID, SECRETARY), "ERR_ASSIGNMENT_NOT_FOUND"),
        (api_client.get_rider(MISSING_UUID, OFFICER), "ERR_RIDER_NOT_FOUND"),
        (api_client.get_horse(MISSING_UUID, OFFICER), "ERR_HORSE_NOT_FOUND"),
        (api_client.get_entry(MISSING_UUID, SECRETARY), "ERR_ENTRY_NOT_FOUND"),
        (api_client.get_class_entry(MISSING_UUID, SECRETARY), "ERR_CLASS_ENTRY_NOT_FOUND"),
        (api_client.get_compliance_case(MISSING_UUID, STEWARD), "ERR_COMPLIANCE_CASE_NOT_FOUND"),
    ]
    for response, error_id in probes:
        payload = validate_error(response, error_id, 404)
        assert payload["error_id"] == error_id
        assert isinstance(payload["message"], str) and payload["message"]
        assert response.json()["response_type"] == "error"


def test_omitting_any_required_input_is_rejected_and_writes_nothing():
    """Five probes each drop exactly one input that carries no declared default — the entry's
    horse, the entry's rider, the show's stall fee, the class's purse share and the division's
    purse share — and every one is a shape rejection rather than a stored row with a hole in it.
    Neither the entry collection nor the division collection grew.

    PRD §2.8: "Payload shape itself is checked before any of this: required fields present, enum values drawn from their declared member sets, integers inside their declared ranges, datetimes parseable as ISO 8601, and conditionally required fields honoured."
    PRD §2.8: "A violation is `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.5: "An `Exhibitor` submits an entry to a licensed show, naming the `rider_id` competing and the `horse_id` competing, with an optional `requested_stall_count` defaulting to 0 and never negative."
    PRD §3.1: "`stall_capacity` is the number of stalls on the grounds and `stall_fee_cents` the per-stall charge that will appear on entry invoices; neither may be negative."
    PRD §3.2: "Creating one requires a `class_number` — the prize-list number, at least 1, and unique across every class of the same show, with a collision reported as `ERR_CLASS_NUMBER_DUPLICATE` — a printed `name`, a `jump_height_cm`, a per-horse `entry_fee_cents`, a `class_share_bp` between 0 and 10000 inclusive claiming a slice of the division's allotment, and a `max_entries` ceiling of at least 1."
    PRD §3.2: "It claims a slice of the show's purse with `division_share_bp`, a basis-point figure between 0 and 10000 inclusive."

    Design: Corner/entities/entry_missing_required_fields_rejected
    """
    show = create_show()
    division = create_division(show["id"])
    rider = create_rider()
    horse = create_horse()
    exhibitor = make_exhibitor_headers(rider["id"])

    validate_error(
        api_client.create_entry(show["id"], {"rider_id": rider["id"]}, exhibitor),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api_client.create_entry(show["id"], {"horse_id": horse["id"]}, exhibitor),
        "ERR_INVALID_REQUEST",
        422,
    )

    show_payload = create_show_payload(name="Winter Classic", federation_show_id="FED-2435")
    del show_payload["stall_fee_cents"]
    validate_error(api_client.create_show(show_payload, SECRETARY), "ERR_INVALID_REQUEST", 422)

    class_payload = create_class_payload()
    del class_payload["class_share_bp"]
    validate_error(
        api_client.create_class(division["id"], class_payload, SECRETARY),
        "ERR_INVALID_REQUEST",
        422,
    )

    division_payload = create_division_payload(
        name="Open Equitation", discipline="EQUITATION", age_group="JUNIOR",
        min_jump_height_cm=80, max_jump_height_cm=100,
    )
    del division_payload["division_share_bp"]
    validate_error(
        api_client.create_division(show["id"], division_payload, SECRETARY),
        "ERR_INVALID_REQUEST",
        422,
    )

    _entries, entry_meta = validate_paginated(
        api_client.list_entries(SECRETARY, params={"show_id": show["id"]})
    )
    assert entry_meta["total_count"] == 0
    _divisions, division_meta = validate_paginated(
        api_client.list_show_divisions(show["id"], SECRETARY)
    )
    assert division_meta["total_count"] == 1


def test_omitted_optional_inputs_land_on_their_declared_defaults():
    """A ring created with nothing but a name and a surface takes the declared 100-point footing
    seed, the 10-minute turnover buffer and the 12-horse warm-up capacity — a buffer silently
    defaulted to zero would change every later duration estimate. The division's jump-off flag
    defaults to false, the class's qualifier reference to null, and the entry's stall request to
    zero, which is why a zero-stall entry leaves the stall ledger untouched.

    PRD §3.3: "Three optional figures shape how the ring behaves: `footing_condition_score`, a seed value from 0 to 100 inclusive that defaults to 100; `turnover_buffer_minutes`, the drag-and-reset time required between consecutive occupancies, defaulting to 10 and never negative; and `warmup_capacity_horses`, the maximum number of horses permitted in the ring's warm-up arena at one time, defaulting to 12 and at least 1."
    PRD §3.2: "And it declares with `jumpoff_enabled` whether its classes run a jump-off; the flag defaults to false and only affects duration estimation for jumper classes."
    PRD §3.2: "A class may optionally name, through `qualifier_for_class_id`, the championship class it qualifies riders for; the field defaults to null."
    PRD §3.5: "An `Exhibitor` submits an entry to a licensed show, naming the `rider_id` competing and the `horse_id` competing, with an optional `requested_stall_count` defaulting to 0 and never negative."
    PRD §3.5: "A new entry has `verification_status` of `RECEIVED`, `settlement_status` of `UNBILLED`, `assigned_stall_count` of 0, all five settlement figures — `class_fee_cents_total`, `stall_fee_cents`, `preliminary_subtotal_cents`, `office_fee_cents` and `total_due_cents` — at 0, and `refunded_cents` at 0."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    show = create_show()
    division = validate_success(
        api_client.create_division(
            show["id"],
            {
                "name": "Open Jumper",
                "discipline": "JUMPER",
                "age_group": "OPEN",
                "min_jump_height_cm": 100,
                "max_jump_height_cm": 130,
                "division_share_bp": 3333,
            },
            SECRETARY,
        ),
        201,
    )
    assert division["jumpoff_enabled"] is False

    show_class = create_class(division["id"])
    assert show_class["qualifier_for_class_id"] is None

    approve_license(show["id"])

    ring = validate_success(
        api_client.create_ring(show["id"], {"name": "Ring Z", "surface_type": "GRASS"}, SECRETARY),
        201,
    )
    assert ring["footing_condition_score"] == 100
    assert ring["turnover_buffer_minutes"] == 10
    assert ring["warmup_capacity_horses"] == 12
    assert ring["status"] == "AVAILABLE"

    rider = create_rider()
    horse = create_horse()
    entry = validate_success(
        api_client.create_entry(
            show["id"],
            {"rider_id": rider["id"], "horse_id": horse["id"]},
            make_exhibitor_headers(rider["id"]),
        ),
        201,
    )
    assert_entry(entry)
    assert entry["requested_stall_count"] == 0
    assert entry["assigned_stall_count"] == 0
    assert entry["verification_status"] == "RECEIVED"
    assert entry["settlement_status"] == "UNBILLED"

    after = get_show(show["id"])
    assert after["reserved_stall_count"] == 0
    assert after["available_stall_count"] == 40
    assert get_class(show_class["id"])["qualifier_for_class_id"] is None


def test_coggins_expiry_is_365_days_after_the_draw_and_membership_is_read_off_the_clock():
    """A sample drawn on 1 March 2026 expires on 1 March 2027, because 2026 is not a leap year:
    a "+1 calendar year" or a "+366 days" implementation lands on a different day. The June 2025
    draw expires in June 2026, both horses come back ELIGIBLE without ever having been told so,
    and the two riders' membership is derived against the clock's 1 August 2026 startup instant.

    PRD §3.4: "A horse is registered with a `federation_registration_number`, its registered `name`, an `owner_name` and the `coggins_drawn_on` instant at which its EIA blood sample was taken."
    PRD §3.4: "The service derives `coggins_expires_on` as `coggins_drawn_on` plus 365 days, and sets `eligibility_status` to `ELIGIBLE`."
    PRD §3.4: "Membership is not stored as a settled state: `membership_status` is re-derived on every read as `ACTIVE` when the logical clock is strictly before `membership_expires_on` and `LAPSED` otherwise."
    PRD §2.6: "On startup the logical current instant is exactly `2026-08-01T00:00:00Z`, and it stays there until a `FederationOfficer` moves it by supplying a `to_iso8601` instant to the clock-setting capability described in §4."

    Design: Corner/entities/coggins_expiry_derived_from_draw_date
    """
    fresh = validate_success(
        api_client.create_horse(
            create_horse_payload(
                federation_registration_number="H-2001",
                name="Comet",
                coggins_drawn_on="2026-03-01T00:00:00Z",
            ),
            OFFICER,
        ),
        201,
    )
    assert_horse(fresh)
    assert fresh["coggins_expires_on"] == "2027-03-01T00:00:00Z"
    assert fresh["eligibility_status"] == "ELIGIBLE"

    stale = create_horse(
        federation_registration_number="H-2009", name="Stale",
        coggins_drawn_on="2025-06-01T00:00:00Z",
    )
    assert stale["coggins_expires_on"] == "2026-06-01T00:00:00Z"
    assert stale["eligibility_status"] == "ELIGIBLE"

    lapsed = create_rider(
        federation_member_number="M-1009", full_name="Lapsed Rider",
        membership_expires_on="2026-07-15T00:00:00Z",
    )
    active = create_rider(
        federation_member_number="M-1001", full_name="Ada Rider",
        membership_expires_on="2027-06-30T00:00:00Z",
    )
    assert validate_success(api_client.get_rider(lapsed["id"], OFFICER))["membership_status"] == "LAPSED"
    assert validate_success(api_client.get_rider(active["id"], OFFICER))["membership_status"] == "ACTIVE"


def test_the_standings_submission_is_stamped_with_the_raising_secretarys_own_user_id():
    """The submission's only system-sourced field comes from the acting secretary's header, not
    from a body that carries nothing but the version guard. At PREPARED neither standings body has
    answered yet, so both body references are null and both point totals are 0.

    PRD §3.8: "The submission is created with `status` of `PREPARED`, `submitted_by_user_id` set to the raising secretary's `X-User-ID`, `national_body_reference` and `regional_body_reference` both null, and `national_points_total` and `regional_points_total` both 0."
    PRD §3.8: "The class moves `RESULTS_POSTED → POINTS_SUBMITTED` and its `version` increments."
    PRD §2.5: "Every persisted resource carries a server-minted `id`: a UUID with no type prefix, assigned at creation and never reused or rewritten."
    PRD §2.7: "Raising a standings submission for a class — `POST /classes/{id}/point-submissions` — requires `expected_class_version` in the request body, carrying the client's last observed `version` of the target class."

    Design: Corner/entities/point_submission_stamps_submitting_user
    """
    ctx = build_point_submission(entry_count=3, actual_minutes=26)
    submission = ctx["submission"]

    assert_point_submission(submission)
    assert submission["submitted_by_user_id"] == SHOW_SECRETARY_USER_ID
    assert submission["class_id"] == ctx["class_id"]
    assert submission["status"] == "PREPARED"
    assert submission["national_body_reference"] is None
    assert submission["regional_body_reference"] is None
    assert submission["national_points_total"] == 0
    assert submission["regional_points_total"] == 0
    assert submission["version"] == 1

    assert get_class(ctx["class_id"])["status"] == "POINTS_SUBMITTED"


def test_enum_members_numeric_ranges_and_the_inter_field_band_are_all_enforced():
    """Ten probes walk the declared member sets and ranges: an invented competition level, a
    negative purse, an unparseable instant, an invented discipline, a share one basis point over
    the ceiling, an inverted height band, an invented surface, a licence grade above 4, an empty
    roles array and a zero entry ceiling. Every one is a shape rejection, and none of them left a
    division, a ring or a class behind.

    PRD §2.8: "Payload shape itself is checked before any of this: required fields present, enum values drawn from their declared member sets, integers inside their declared ranges, datetimes parseable as ISO 8601, and conditionally required fields honoured."
    PRD §3.1: "`prize_money_pool_cents` is the total purse the organizer has posted, in cents, and may not be negative."
    PRD §3.2: "The division fixes an inclusive fence-height band with `min_jump_height_cm` and `max_jump_height_cm`, neither negative and the upper bound at least equal to the lower."
    PRD §3.2: "It claims a slice of the show's purse with `division_share_bp`, a basis-point figure between 0 and 10000 inclusive."
    PRD §3.3: "A `ShowSecretary` adds one with a `name` such as "Grand Prix Field" and a `surface_type` of `SAND_FIBER`, `GRASS` or `CLAY`."
    PRD §3.4: "An official is registered with a `federation_official_id` licence number, a `full_name`, a non-empty `license_roles` array whose members are drawn from `JUDGE`, `STEWARD` and `TECHNICAL_DELEGATE`, a `license_level` grade from 1 to 4 inclusive, a non-empty `licensed_disciplines` array whose members are drawn from `HUNTER`, `JUMPER`, `EQUITATION` and `DRESSAGE`, and a `license_expires_on` instant."

    Design: Corner/entities/enum_and_range_constraints_rejected
    """
    show = create_show()
    division = create_division(show["id"])

    validate_error(
        api_client.create_show(
            create_show_payload(name="County Fair", federation_show_id="FED-9001",
                                competition_level="COUNTY"),
            SECRETARY,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api_client.create_show(
            create_show_payload(name="Negative Pool", federation_show_id="FED-9002",
                                prize_money_pool_cents=-1),
            SECRETARY,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api_client.create_show(
            create_show_payload(name="Bad Date", federation_show_id="FED-9003",
                                start_utc="not-a-datetime"),
            SECRETARY,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    validate_error(
        api_client.create_division(
            show["id"],
            create_division_payload(name="Saddlebred", discipline="SADDLEBRED",
                                    min_jump_height_cm=0, max_jump_height_cm=0,
                                    division_share_bp=1000),
            SECRETARY,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api_client.create_division(
            show["id"],
            create_division_payload(name="Over Share", discipline="HUNTER",
                                    min_jump_height_cm=80, max_jump_height_cm=120,
                                    division_share_bp=10001),
            SECRETARY,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api_client.create_division(
            show["id"],
            create_division_payload(name="Inverted Band", discipline="HUNTER",
                                    min_jump_height_cm=130, max_jump_height_cm=120,
                                    division_share_bp=1000),
            SECRETARY,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    validate_error(
        api_client.create_ring(show["id"], {"name": "Mud Ring", "surface_type": "MUD"}, SECRETARY),
        "ERR_INVALID_REQUEST",
        422,
    )

    validate_error(
        api_client.create_official(
            create_official_payload(federation_official_id="OF-9001", full_name="Over Licensed",
                                    license_level=5),
            OFFICER,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    validate_error(
        api_client.create_official(
            create_official_payload(federation_official_id="OF-9002", full_name="No Chairs",
                                    license_roles=[]),
            OFFICER,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    validate_error(
        api_client.create_class(
            division["id"], create_class_payload(name="Zero Cap", max_entries=0), SECRETARY
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    _divisions, division_meta = validate_paginated(
        api_client.list_show_divisions(show["id"], SECRETARY)
    )
    assert division_meta["total_count"] == 1
    _rings, ring_meta = validate_paginated(api_client.list_show_rings(show["id"], SECRETARY))
    assert ring_meta["total_count"] == 0
    _classes, class_meta = validate_paginated(
        api_client.list_classes(SECRETARY, params={"division_id": division["id"]})
    )
    assert class_meta["total_count"] == 0


def test_a_class_hangs_off_a_real_division_and_may_only_qualify_inside_its_own_show():
    """An unknown parent division is a typed 404 that creates nothing. A qualifier reference that
    leaves the show is refused by the same rule that forbids cycles — the reference must stay
    inside one show — while a two-hop chain within one show is a legal directed path.

    PRD §2.8: "The not-found codes are per resource type: `ERR_SHOW_NOT_FOUND`, `ERR_RING_NOT_FOUND`, `ERR_DIVISION_NOT_FOUND`, `ERR_CLASS_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_CLASS_ENTRY_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_POINT_SUBMISSION_NOT_FOUND`, `ERR_COMPLIANCE_CASE_NOT_FOUND` and `ERR_COVERAGE_SHIFT_NOT_FOUND`. All carry HTTP 404."
    PRD §3.2: "The named class must belong to the same show, and following the chain of `qualifier_for_class_id` references transitively from the new class must never arrive back at the new class itself."
    PRD §3.2: "A reference outside the show, or one that would close a cycle, is refused with `ERR_QUALIFIER_CYCLE`."
    PRD §3.2: "The chain is therefore a directed acyclic graph within one show."

    Design: Corner/entities/class_creation_requires_division_of_this_show
    """
    show_one = create_show()
    division_one = create_division(show_one["id"])
    class_101 = create_class(division_one["id"])
    class_102 = create_class(
        division_one["id"], class_number=102, name="Jumper Qualifier", jump_height_cm=110,
        class_share_bp=1000, qualifier_for_class_id=class_101["id"],
    )

    show_two = create_show(
        name="Spring Classic", federation_show_id="FED-2436",
        start_utc="2027-04-10T13:00:00Z", end_utc="2027-04-13T22:00:00Z",
        entry_close_utc="2027-04-01T00:00:00Z", prize_money_pool_cents=500000,
        stall_capacity=20,
    )
    division_two = create_division(show_two["id"])

    validate_error(
        api_client.create_class(
            MISSING_UUID,
            create_class_payload(class_number=901, name="Orphan Class", class_share_bp=1000),
            SECRETARY,
        ),
        "ERR_DIVISION_NOT_FOUND",
        404,
    )

    validate_error(
        api_client.create_class(
            division_two["id"],
            create_class_payload(class_number=301, name="Cross Show Qualifier",
                                 class_share_bp=1000,
                                 qualifier_for_class_id=class_101["id"]),
            SECRETARY,
        ),
        "ERR_QUALIFIER_CYCLE",
        409,
    )

    two_hop = validate_success(
        api_client.create_class(
            division_one["id"],
            create_class_payload(class_number=103, name="Two Hop Qualifier", jump_height_cm=100,
                                 class_share_bp=1000,
                                 qualifier_for_class_id=class_102["id"]),
            SECRETARY,
        ),
        201,
    )
    assert_class(two_hop)
    assert two_hop["qualifier_for_class_id"] == class_102["id"]

    _rows, meta = validate_paginated(
        api_client.list_classes(SECRETARY, params={"division_id": division_two["id"]})
    )
    assert meta["total_count"] == 0


def test_the_class_entry_junction_carries_both_of_its_filters_independently():
    """One entry sits in two classes and one class holds two entries, so the junction's two
    filters answer with two rows each while the pair that was never linked answers with an empty
    page rather than the whole entry's rows. Both classes count what they actually hold.

    PRD §3.5: "An `Exhibitor` who owns the entry adds it to a specific class by naming the `entry_id` and the `class_id`."
    PRD §3.5: "A new class entry has `status` of `ENTERED`, or `CONFIRMED` immediately when the parent entry is already both `ACCEPTED` and `PAID`."
    PRD §3.5: "Creation recomputes the class's `entry_count`, `confirmed_entry_count` and `point_eligible`, and increments the class's `version`."
    PRD §3.2: "`entry_count` is the number of class entries on the class whose `status` is `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED` — scratched rows drop out of it — and it is `entry_count` that `max_entries` caps."
    PRD §2.4: "Filters are exact-match on the named field and may be combined; supplying none returns the whole collection."

    Design: Corner/entities/class_entry_junction_links_many_to_many
    """
    show = create_show()
    division = create_division(show["id"])
    class_101 = create_class(division["id"])
    class_102 = create_class(
        division["id"], class_number=102, name="Open Jumper 1.10m", jump_height_cm=110,
        class_share_bp=1000,
    )
    class_103 = create_class(
        division["id"], class_number=103, name="Jumper Championship", jump_height_cm=130,
        class_share_bp=1000, qualifier_for_class_id=class_101["id"],
    )
    approve_license(show["id"])
    open_class(class_101["id"])
    open_class(class_102["id"])

    rows = []
    for _ in range(2):
        rider = create_rider()
        horse = create_horse()
        headers = make_exhibitor_headers(rider["id"])
        entry = validate_success(
            api_client.create_entry(
                show["id"], create_entry_payload(rider["id"], horse["id"]), headers
            ),
            201,
        )
        rows.append({"entry_id": entry["id"], "headers": headers})

    def link(row, class_id):
        return validate_success(
            api_client.create_class_entry(
                {"entry_id": row["entry_id"], "class_id": class_id}, row["headers"]
            ),
            201,
        )

    ce_1a = link(rows[0], class_101["id"])
    ce_1b = link(rows[0], class_102["id"])
    ce_2a = link(rows[1], class_101["id"])

    for row in (ce_1a, ce_1b, ce_2a):
        assert_class_entry(row)
        assert row["status"] == "ENTERED"
    assert len({ce_1a["id"], ce_1b["id"], ce_2a["id"]}) == 3

    _by_entry, by_entry_meta = validate_paginated(
        api_client.list_class_entries(SECRETARY, params={"entry_id": rows[0]["entry_id"]})
    )
    assert by_entry_meta["total_count"] == 2

    _by_class, by_class_meta = validate_paginated(
        api_client.list_class_entries(SECRETARY, params={"class_id": class_101["id"]})
    )
    assert by_class_meta["total_count"] == 2

    unlinked, unlinked_meta = validate_paginated(
        api_client.list_class_entries(
            SECRETARY, params={"entry_id": rows[1]["entry_id"], "class_id": class_102["id"]}
        )
    )
    assert unlinked == []
    assert unlinked_meta["total_count"] == 0

    assert get_class(class_101["id"])["entry_count"] == 2
    assert get_class(class_102["id"])["entry_count"] == 1

    chain, chain_meta = validate_paginated(
        api_client.list_classes(SECRETARY, params={"qualifier_for_class_id": class_101["id"]})
    )
    assert chain_meta["total_count"] == 1
    assert [row["id"] for row in chain] == [class_103["id"]]
