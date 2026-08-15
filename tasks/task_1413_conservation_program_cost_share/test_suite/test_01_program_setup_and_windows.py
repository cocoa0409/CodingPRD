"""Program configuration, defaults, window overlap, and applicant registration."""
from test_helpers import (
    ApiErrorId,
    add_criterion,
    add_pool,
    add_rate,
    api_client,
    assert_applicant,
    assert_program,
    create_program,
    create_program_payload,
    is_valid_uuid,
    open_program,
    register_applicant,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_program_creation_defaults_applied(api):
    """PRD §3.1: "`spot_check_modulus`, which defaults to 5 and controls how
    payment requests are sampled for mandatory spot checks (§3.7), and
    `advance_cap_pct`, which defaults to 0.5 — one-half — and caps the
    historically-underserved advance described in §3.6" and "A new program
    starts in `SETUP` with its `ranking_run_count` at zero."

    Design: Corner/entities/program_creation_defaults_applied
    """
    resp = api.create_program(create_program_payload(), ADMIN)
    program = validate_success(resp, 201)
    assert_program(program)
    assert program["spot_check_modulus"] == 5, "spot_check_modulus default must be 5"
    assert program["advance_cap_pct"] == 0.5, "advance_cap_pct default must be 0.5"
    assert program["status"] == "SETUP"
    assert program["ranking_run_count"] == 0


def test_program_create_ignores_client_supplied_id_and_version(api):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix." and
    "`version` is a system-managed integer that increments by one on every
    mutation of the resource and underpins the optimistic concurrency rules
    of §2.10."

    Design: Corner/entities/program_create_client_id_input_ignored
    """
    supplied_id = "11111111-1111-4111-8111-111111111111"
    resp = api.create_program(
        create_program_payload(id=supplied_id, version=99), ADMIN
    )
    program = validate_success(resp, 201)
    assert is_valid_uuid(program["id"]), "server must mint a UUID id"
    assert program["id"] != supplied_id, "client-supplied id must be ignored"
    assert isinstance(program["version"], int), "version must be system-managed"
    assert program["version"] != 99, "client-supplied version must be ignored"


def test_open_requires_minimal_config_then_succeeds(api):
    """PRD §3.1: "Opening the program moves it from `SETUP` to `OPEN` and is
    allowed only once the configuration is minimally complete: at least one
    pool, at least one rate, and at least one ranking criterion must exist, or
    the attempt fails with `ERR_PROGRAM_INCOMPLETE_CONFIG` (HTTP 409)."

    Design: Corner/endpoints/program_open_requires_config
    """
    program = create_program()
    err_resp = api.open_program(program["id"], ADMIN)
    validate_error(err_resp, ApiErrorId.ERR_PROGRAM_INCOMPLETE_CONFIG)

    add_pool(program["id"], "GENERAL", 100000)
    add_rate(program["id"])
    add_criterion(program["id"])
    opened = validate_success(api.open_program(program["id"], ADMIN), 200)
    assert opened["status"] == "OPEN"


def test_run_ranking_requires_closed_and_single_run(api):
    """PRD §3.3: "the selection waterfall, which is permitted only while the
    program is `CLOSED` (otherwise `ERR_PROGRAM_NOT_CLOSED`, HTTP 409) and only
    once per program: `ranking_run_count` must still be zero, and a second
    invocation is rejected with `ERR_RANKING_ALREADY_RUN` (HTTP 409)."

    Design: Corner/endpoints/run_ranking_requires_closed_and_single_run
    """
    program = create_program()
    add_pool(program["id"], "GENERAL", 100000)
    add_rate(program["id"])
    add_criterion(program["id"])
    open_program(program["id"])

    err_resp = api.run_ranking(program["id"], ADMIN)
    validate_error(err_resp, ApiErrorId.ERR_PROGRAM_NOT_CLOSED)

    from test_helpers import close_program, run_ranking
    close_program(program["id"])
    result = run_ranking(program["id"])
    assert result["ranked_count"] == 0, "empty candidate set is a legal run"

    err_resp2 = api.run_ranking(program["id"], ADMIN)
    validate_error(err_resp2, ApiErrorId.ERR_RANKING_ALREADY_RUN)


def test_duplicate_rate_and_criterion_rejected(api):
    """PRD §3.1: "`practice_code` (one of `COVER_CROP`, `PRESCRIBED_GRAZING`,
    `WATERING_FACILITY`, `FENCE`, or `NUTRIENT_MANAGEMENT`, unique within the
    program — a second rate for the same code is rejected with
    `ERR_DUPLICATE_RATE`)" and "A **Ranking Criterion** contributes a
    `criterion_code` unique within the program (duplicates are rejected with
    `ERR_DUPLICATE_CRITERION`)".

    Design: Corner/entities/rate_and_criterion_uniqueness_rejected
    """
    program = create_program()
    add_rate(program["id"], practice_code="FENCE", standard_rate_cents=300,
             hu_rate_cents=360, lifespan_years=10)
    add_criterion(program["id"], criterion_code="SOIL_HEALTH", weight=1.0, max_points=40)

    dup_rate = api.create_rate(
        program["id"],
        {
            "practice_code": "FENCE",
            "unit": "FOOT",
            "standard_rate_cents": 301,
            "hu_rate_cents": 361,
            "lifespan_years": 10,
        },
        ADMIN,
    )
    validate_error(dup_rate, ApiErrorId.ERR_DUPLICATE_RATE)

    dup_criterion = api.create_criterion(
        program["id"],
        {"criterion_code": "SOIL_HEALTH", "weight": 2.0, "max_points": 40},
        ADMIN,
    )
    validate_error(dup_criterion, ApiErrorId.ERR_DUPLICATE_CRITERION)


def test_applicant_hu_flag_computed(api):
    """PRD §3.2: "the derived flag `historically_underserved` is true whenever
    the category is anything other than `NONE`, and it drives both the higher
    payment rate of §3.4 and the advance-payment eligibility of §3.6."

    Design: Corner/entities/applicant_hu_flag_computed
    """
    hu = register_applicant(legal_name="H", hu_category="LIMITED_RESOURCE",
                            parcel_ids=("P-1",))
    std = register_applicant(legal_name="S", hu_category="NONE", parcel_ids=("P-2",))
    assert_applicant(hu)
    assert_applicant(std)
    assert hu["historically_underserved"] is True
    assert std["historically_underserved"] is False

    # A client-supplied value for the derived flag is not honored: the server
    # derives it from the category.
    resp = api.create_applicant(
        {
            "legal_name": "H2",
            "hu_category": "VETERAN",
            "parcel_ids": ["P-3"],
            "historically_underserved": False,
        },
        ADMIN,
    )
    overridden = validate_success(resp, 201)
    assert overridden["historically_underserved"] is True


def test_applicant_create_invalid_enum_rejected(api):
    """PRD §3.2: "The category is one of `NONE`, `BEGINNING_FARMER`,
    `SOCIALLY_DISADVANTAGED`, `LIMITED_RESOURCE`, or `VETERAN`, defaulting to
    `NONE`". PRD §2.6 item 8: "Shape, uniqueness, and cardinality — required
    fields present and correctly typed, valid enum values, non-empty
    documentation".

    Design: Corner/entities/applicant_create_invalid_enum_rejected
    """
    resp = api.create_applicant(
        {"legal_name": "X", "hu_category": "SUPREME_BEING", "parcel_ids": ["P-1"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_window_overlap_touching_conflicts(api):
    """PRD §3.1: "for the same `state_code`, a new program's window must not
    intersect any existing program's window, and because the intervals are
    closed at both ends, windows that merely touch at a single instant still
    conflict — the new program is rejected with `ERR_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/program_window_touching_conflict_inclusive
    """
    create_program(
        program_name="P1",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
        state_code="IA",
    )
    touching = api.create_program(
        create_program_payload(
            program_name="P2",
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-10-01T00:00:00Z",
            state_code="IA",
        ),
        ADMIN,
    )
    validate_error(touching, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_window_disjoint_or_other_state_allowed(api):
    """PRD §3.1: "for the same `state_code`, a new program's window must not
    intersect any existing program's window, and because the intervals are
    closed at both ends, windows that merely touch at a single instant still
    conflict — the new program is rejected with `ERR_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/program_window_touching_conflict_inclusive
    """
    create_program(
        program_name="P1",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
        state_code="IA",
    )
    # Starts one day after P1's window closes: fully disjoint, must succeed.
    disjoint = validate_success(
        api.create_program(
            create_program_payload(
                program_name="P3",
                window_start="2026-09-02T00:00:00Z",
                window_end="2026-10-01T00:00:00Z",
                state_code="IA",
            ),
            ADMIN,
        ),
        201,
    )
    assert disjoint["program_name"] == "P3"
    # Identical window under a different state_code governs a different
    # resource and must succeed.
    other_state = validate_success(
        api.create_program(
            create_program_payload(
                program_name="P4",
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-09-01T00:00:00Z",
                state_code="NE",
            ),
            ADMIN,
        ),
        201,
    )
    assert other_state["state_code"] == "NE"
