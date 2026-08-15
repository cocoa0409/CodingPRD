"""Job booking shape, creation validation, and OCC-guarded amendment."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    set_clock,
    create_tx_job,
    create_job_payload,
    leg_spec,
    list_job_legs,
    quote_job,
    get_job,
    amend_job_payload,
    make_carrier_rep_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_job_creation_creates_legs_in_route_order(api):
    """PRD §3.2: "Booking creates the job with its `job_status` field at `DRAFT`
    and, in the same operation, creates one route leg per element of `legs`,
    each with its `leg_status` at `PENDING`; the job's leg listing returns them
    ordered by `sequence_index` ascending."
    PRD §3.4: "Before any survey is accepted, the verdict remains `UNKNOWN`"

    Design: Corner/entities/job_creation_creates_legs
    """
    carrier = register_carrier(10_000_000, "Two Leg Co")
    set_clock("2026-08-05T00:00:00Z")
    legs = [
        leg_spec("TX", 0, 120, "2026-08-10T09:00:00Z", "2026-08-10T13:00:00Z", 180),
        leg_spec("OK", 1, 100, "2026-08-10T13:30:00Z", "2026-08-10T15:00:00Z", 180),
    ]
    job = create_tx_job(
        carrier,
        load_description="Two-state run",
        window_start_at="2026-08-10T09:00:00Z",
        window_end_at="2026-08-10T15:00:00Z",
        legs=legs,
    )
    assert job["job_status"] == "DRAFT"
    assert job["version"] == 1

    rows, meta = validate_paginated(api.list_job_legs(job["id"], DISPATCHER))
    assert meta["total_count"] == 2
    assert rows[0]["state_code"] == "TX" and rows[0]["sequence_index"] == 0
    assert rows[1]["state_code"] == "OK" and rows[1]["sequence_index"] == 1
    for row in rows:
        assert row["leg_status"] == "PENDING"
        assert row["clearance_verdict"] == "UNKNOWN"
        assert row["police_confirmed"] is False


def test_window_and_dimension_range_rejected(api):
    """PRD §3.2: "The planned movement is bounded by `window_start_at` and
    `window_end_at`, with the end strictly later than the start"
    PRD §2.11: "dimensions greater than zero, `valid_until` later than
    `valid_from`, `window_end_at` later than `window_start_at`,
    `planned_exit_at` later than `planned_entry_at` ... Violations yield
    `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/window_and_dimension_range_rejected
    """
    carrier = register_carrier(10_000_000, "Range Co")
    rep = make_carrier_rep_headers(carrier["id"])

    bad_window = create_job_payload(
        carrier["id"],
        load_description="Bad window",
        window_start_at="2026-08-10T13:00:00Z",
        window_end_at="2026-08-10T09:00:00Z",
    )
    resp1 = api.create_job(bad_window, rep)
    validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

    bad_width = create_job_payload(carrier["id"], load_description="Zero width", width_inches=0)
    resp2 = api.create_job(bad_width, rep)
    validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_jobs(DISPATCHER))
    assert rows == [] and meta["total_count"] == 0, "no job may be persisted by a rejected booking"


def test_unsupported_state_code_rejected(api):
    """PRD §3.2: "each element specifies `state_code` (one of `TX`, `OK`, `KS`,
    `LA`; any other value is rejected with `ERR_INVALID_REQUEST`)"

    Design: Corner/entities/unsupported_state_code_rejected
    """
    carrier = register_carrier(10_000_000, "California Here")
    payload = create_job_payload(
        carrier["id"],
        load_description="CA run",
        legs=[leg_spec("CA", 0, 120, "2026-08-10T09:00:00Z", "2026-08-10T13:00:00Z", 180)],
    )
    resp = api.create_job(payload, make_carrier_rep_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_jobs(DISPATCHER))
    assert rows == [] and meta["total_count"] == 0


def test_invalid_enum_value_rejected(api):
    """PRD §2.11: "Violations yield `ERR_INVALID_REQUEST` (HTTP 400); for an
    out-of-membership enum value the server may instead return
    `ERR_INVALID_ENUM_VALUE` (HTTP 400), and both live at this priority."

    Design: Corner/entities/invalid_enum_value_rejected
    """
    carrier = register_carrier(10_000_000, "Enum Co")
    job = create_tx_job(carrier, load_description="Enum job")
    quote_job(job["id"])
    accept = validate_success(api.accept_quote(job["id"], make_carrier_rep_headers(carrier["id"])))
    assert accept["job_status"] == "BOOKED"
    leg_id = list_job_legs(job["id"])[0]["id"]

    resp = api.create_assignment(leg_id, {"position": "MIDDLE"}, DISPATCHER)
    actual = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_ENUM_VALUE, ApiErrorId.ERR_INVALID_REQUEST]
    )
    assert resp.status_code == 400, f"expected 400, got {resp.status_code} ({actual})"

    rows, meta = validate_paginated(api.list_leg_assignments(leg_id, DISPATCHER))
    assert rows == [] and meta["total_count"] == 0, "no assignment may be created by a rejected offer"


def test_occ_job_amend_stale_version(api):
    """PRD §2.9: "Amending a job requires the request to carry
    `expected_job_version`, holding the job `version` the client last observed.
    If that value does not match the job's current `version` — for example
    because a quote was generated, or another amendment was applied, since the
    client read the job — the amendment is rejected with `ERR_STALE_JOB_VERSION`
    (HTTP 412)."
    PRD §3.2: "Amending a `QUOTED` job reverts it to `DRAFT` and discards the
    quote entirely — `quoted_cents`, `quoted_at`, and `quote_expires_at` are
    cleared to null and `total_escort_positions` to 0"
    PRD §3.2: "Whenever at least one of the four dimensional fields changes,
    every leg currently in `DETERMINED` is reset to `PENDING` with its
    requirement fields returned to their defaults"

    Design: Corner/cross_cutting_layers/occ_job_amend_stale_version
    """
    carrier = register_carrier(10_000_000, "OCC Job Co")
    job = create_tx_job(carrier, load_description="OCC")
    quoted = quote_job(job["id"])
    observed_version = quoted["version"]
    assert quoted["job_status"] == "QUOTED"

    # First amendment at the observed version succeeds and reverts QUOTED -> DRAFT.
    resp = api.amend_job(job["id"], amend_job_payload(observed_version, width_inches=171), DISPATCHER)
    amended = validate_success(resp)
    assert amended["job_status"] == "DRAFT"
    assert amended["quoted_cents"] is None
    assert amended["quoted_at"] is None
    assert amended["quote_expires_at"] is None
    assert amended["total_escort_positions"] == 0
    assert amended["width_inches"] == 171
    assert amended["version"] == observed_version + 1

    legs = list_job_legs(job["id"])
    assert legs[0]["leg_status"] == "PENDING", "a dimensional amendment resets DETERMINED legs"

    # Replaying the stale observed version is rejected with 412.
    resp2 = api.amend_job(job["id"], amend_job_payload(observed_version, width_inches=172), DISPATCHER)
    validate_error(resp2, ApiErrorId.ERR_STALE_JOB_VERSION)
    current = get_job(job["id"])
    assert current["width_inches"] == 171
    assert current["version"] == observed_version + 1
