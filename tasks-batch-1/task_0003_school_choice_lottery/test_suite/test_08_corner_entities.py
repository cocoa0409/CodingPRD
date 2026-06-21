"""Corner-coverage tests for entities (PRD §3.1, §3.3, §3.4) and the
EnrollmentWindow state machine (PRD §3.2): minimal-payload creation,
missing-id 404s, type-constraint rejections, defaults, initial state, and
terminal-state lockdown.
"""
from test_helpers import (
    set_clock,
    create_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    create_application,
    submit_application,
    advance_window_to_lottery_run,
    list_offers_for_application,
    accept_offer_with_current_version,
    finalize_window,
    get_window,
    api_client,
    TEST_USERS,
    make_anonymous_headers,
    validate_success,
    validate_error,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    ApiErrorId,
)
from test_helpers.factories import (
    create_district_payload,
    create_school_payload,
    create_family_payload,
    run_lottery_payload,
)


# =====================================================================
# Corner / entities — create_district minimal payload returns 201
# =====================================================================

def test_create_district_minimal_payload_returns_201(api):
    """PRD §3.1: "A `DistrictAdmin` begins each cycle by declaring the
    district itself: a unique short `code` (uppercase alphanumeric, between
    3 and 8 characters, globally unique across the system), a human-readable
    `name`, and the district's federal `poverty_index_pct` — the
    catchment-level federal poverty rate, expressed as a percent between 0
    and 100 inclusive with two decimal places. A new district's `status`
    starts as `ACTIVE`."
    PRD §2.4: "The `version` field is an integer that begins at 1 on
    creation and increments by exactly one each time the row is mutated;
    it is the parent token consulted by optimistic concurrency control."

    Design: Corner/entities/create_district_minimal_payload_returns_201
    """
    set_clock("2026-01-01T00:00:00Z")
    payload = create_district_payload(code="DZ1", name="Zeta",
                                      poverty_index_pct=12.50)
    res = api.create_district(payload, TEST_USERS["district_admin_headers"])
    data = validate_success(res, 201)
    assert data["code"] == "DZ1"
    assert data["name"] == "Zeta"
    assert data["poverty_index_pct"] == 12.50
    assert data["status"] == "ACTIVE", (
        f"New district must start as ACTIVE; got {data['status']!r}"
    )
    assert data["version"] == 1, (
        f"New district version must be 1; got {data['version']!r}"
    )
    assert is_valid_uuid(data["id"])


# =====================================================================
# Corner / entities — GET unknown district returns ERR_NOT_FOUND
# =====================================================================

def test_get_district_by_unknown_id_returns_not_found(api):
    """PRD §2.5: "For an endpoint such as the one that reads an application
    by id, the server first confirms the application exists; if it does
    not, the request is rejected with `ERR_NOT_FOUND` and HTTP 404 before
    any deeper check."

    Design: Corner/entities/get_district_by_unknown_id_returns_not_found
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.get_district(NON_EXISTENT_UUID, TEST_USERS["district_admin_headers"])
    err = validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
    assert err["error_id"] == ApiErrorId.ERR_NOT_FOUND.value


# =====================================================================
# Corner / entities — POST /schools missing total_seats → ERR_INVALID_REQUEST
# =====================================================================

def test_create_school_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "Each school is registered with a `district_id` (which must
    point to an `ACTIVE` district), a `code` unique within that district
    (uppercase alphanumeric, 3 to 12 characters), a display `name`, a
    `school_type` of either `NEIGHBORHOOD` or `MAGNET`, an inclusive grade
    band given by `grade_min` and `grade_max` (where kindergarten is grade
    0, `grade_min` must not exceed `grade_max`, and `grade_max` may not
    exceed 12), and a `total_seats` integer that is at least zero."

    Omitting required `total_seats` is a schema/range failure, surfacing as
    ERR_INVALID_REQUEST (PRD §5).

    Design: Corner/entities/create_school_missing_required_field_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DRF", name="ReqF", poverty_index_pct=0.00)
    payload = {
        "district_id": district["id"],
        "code": "SRF",
        "name": "RF",
        "school_type": "MAGNET",
        "grade_min": 0,
        "grade_max": 5,
        # total_seats deliberately omitted
    }
    res = api.create_school(payload, TEST_USERS["district_admin_headers"])
    err = validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert err["error_id"] == ApiErrorId.ERR_INVALID_REQUEST.value


# =====================================================================
# Corner / entities — Family.register default poverty_flag is false
# =====================================================================

def test_family_register_default_poverty_flag_is_false(api):
    """PRD §3.3: "A family registers through the public anonymous endpoint
    by supplying `guardian_email` (which is lowercased and is globally
    unique across all families), `residence_zone_code` (the zone identifier
    that the family lives in), `residence_district_id` (the `id` of an
    `ACTIVE` district where they reside), and `poverty_flag` (a boolean,
    default false, that records whether the family is below the federal
    poverty line for the cycle — a self-declared per-family marker that is
    independent of the catchment-level `poverty_index_pct`)."

    Note: PRD names `poverty_flag` as default false but the field IS
    declared in the payload. We test the declared default by sending a
    payload that does not specify `poverty_flag` and asserting the result
    is false.

    Design: Corner/entities/family_register_default_poverty_flag_is_false
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DDF", name="Def", poverty_index_pct=0.00)
    payload = {
        "guardian_email": "def-default@x.com",
        "residence_zone_code": "ZD",
        "residence_district_id": district["id"],
        # poverty_flag omitted to exercise the default
    }
    res = api.register_family(payload, make_anonymous_headers())
    data = validate_success(res, 201)
    assert data["poverty_flag"] is False, (
        f"Default poverty_flag must be false; got {data['poverty_flag']!r}"
    )


# =====================================================================
# Corner / entities — POST /schools grade_min > grade_max
# =====================================================================

def test_create_school_invalid_grade_range_returns_invalid_request(api):
    """PRD §3.1: "an inclusive grade band given by `grade_min` and
    `grade_max` (where kindergarten is grade 0, `grade_min` must not
    exceed `grade_max`, and `grade_max` may not exceed 12)."

    grade_min=7, grade_max=3 violates "grade_min must not exceed grade_max"
    and surfaces as ERR_INVALID_REQUEST.

    Design: Corner/entities/school_create_invalid_grade_range_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DGR", name="Gr", poverty_index_pct=0.00)
    payload = create_school_payload(district["id"], code="SGR", name="GrInv",
                                    school_type="MAGNET", grade_min=7,
                                    grade_max=3, total_seats=5)
    res = api.create_school(payload, TEST_USERS["district_admin_headers"])
    err = validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert err["error_id"] == ApiErrorId.ERR_INVALID_REQUEST.value


# =====================================================================
# Corner / state_machines — open on already-OPEN window → ERR_INVALID_STATE
# =====================================================================

def test_open_window_when_already_open_returns_invalid_state(api):
    """PRD §3.2: "Opening the window transitions it from `DRAFT` to `OPEN`.
    The operation is rejected with `ERR_INVALID_STATE` if the window is not
    in `DRAFT`."

    Design: Corner/state_machines/open_window_from_already_open_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DST", name="St", poverty_index_pct=0.00)
    window = create_window(district["id"], cycle_label="2026-27-ST")
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    # Second open on a window that is already OPEN.
    res = api.open_window(window["id"], TEST_USERS["district_admin_headers"])
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


# =====================================================================
# Corner / state_machines — newly created window starts in DRAFT
# =====================================================================

def test_newly_created_window_starts_in_draft(api):
    """PRD §3.2: "A `DistrictAdmin` creates an enrollment window in `DRAFT`
    for a given district and cycle."

    Design: Corner/state_machines/window_created_in_initial_state_draft
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DIN", name="Init", poverty_index_pct=0.00)
    res = api.create_window(
        {
            "district_id": district["id"],
            "cycle_label": "2026-27-IN",
            "opens_at": "2026-01-02T00:00:00Z",
            "closes_at": "2026-02-01T00:00:00Z",
            "lottery_runs_at": "2026-02-02T00:00:00Z",
        },
        TEST_USERS["district_admin_headers"],
    )
    data = validate_success(res, 201)
    assert data["status"] == "DRAFT", (
        f"New EnrollmentWindow must start in DRAFT; got {data['status']!r}"
    )
    assert data["version"] == 1


# =====================================================================
# Corner / state_machines — FINALIZED window rejects run-lottery
# =====================================================================

def test_finalized_window_rejects_run_lottery(api):
    """PRD §3.2: "Finalization transitions the window from `LOTTERY_RUN` to
    `FINALIZED` and may proceed only when no application in this window is
    still in `OFFERED` status — that is, every offer has either been
    accepted, declined, or expired."
    PRD §3.2: "Running the lottery transitions the window from `CLOSED` to
    `LOTTERY_RUN`. The operation requires the clock to have reached
    `lottery_runs_at` and the window to be in `CLOSED`; either failure
    surfaces as `ERR_INVALID_STATE` or `ERR_WINDOW_TIMING` as appropriate."

    A FINALIZED window is not CLOSED, so a subsequent run-lottery call must
    fail with ERR_INVALID_STATE.

    Design: Corner/state_machines/finalized_window_terminal_lockdown_run_lottery_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DTL", name="TL", poverty_index_pct=0.00)
    school = create_school(district["id"], code="STL", name="TLs",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-TL")
    family = register_family(district["id"], guardian_email="tl@x.com",
                             residence_zone_code="ZTL", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    # Accept the offer so finalize's "no OFFERED" precondition holds.
    off = list_offers_for_application(app["id"], family_id=family["id"])[0]
    accept_offer_with_current_version(family["id"], off["id"])
    finalize_window(window["id"])
    w_final = get_window(window["id"])
    assert w_final["status"] == "FINALIZED"
    res = api.run_lottery(
        window["id"],
        run_lottery_payload(w_final["version"]),
        TEST_USERS["district_admin_headers"],
    )
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] == ApiErrorId.ERR_INVALID_STATE.value
