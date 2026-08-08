"""Billboard registration fees, lapse cascade, and exclusive-lease interval rules."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID, ApiErrorId,
    make_planner_headers, make_applicant_headers,
    create_billboard, create_registered_billboard, register_billboard,
    create_registered_billboard_with_lease, create_lease, get_billboard, set_clock,
)


# ── Registration fee: round per face then sum (Difficulty) ───────────────────
def test_digital_registration_fee_rounds_per_face_then_sums(api):
    """PRD §3.8: "the base per-face fee is 3333 cents, and for a digital structure each
    face's fee is that base multiplied by 1.5. Critically, the per-face fee is rounded
    half up **before** the faces are summed — so a digital face costs the rounded value
    of 3333 times 1.5 (that is, 5000 cents) and the total is that rounded per-face fee
    multiplied by `face_count`".

    Design: Difficulty/combinatorial_formula/registration_fee_round_per_face_then_sum
    """
    parcel, operator, bb = create_billboard(api, face_count=3, is_digital=True)
    registered = register_billboard(api, bb["id"], operator["id"], 15000)
    assert registered["registration_fee_collected_cents"] == 15000


def test_digital_registration_marks_registered(api):
    """PRD §3.8: "Registering from `UNREGISTERED` or from `LAPSED` sets
    `registration_status` to `REGISTERED`, sets `registration_expires_at` to the current
    instant plus the registration term of 365 days, adds the computed fee to the
    cumulative `registration_fee_collected_cents`, and increments the billboard's
    `version`."

    Design: Difficulty/combinatorial_formula/registration_fee_round_per_face_then_sum
    """
    parcel, operator, bb = create_billboard(api, face_count=3, is_digital=True)
    registered = register_billboard(api, bb["id"], operator["id"], 15000)
    assert registered["registration_status"] == "REGISTERED"


# ── Depth-2 lapse cascade (Difficulty) ───────────────────────────────────────
def test_clock_advance_lapses_registered_billboard(api):
    """PRD §2.5: "Any `REGISTERED` billboard whose `registration_expires_at` is at or
    before the new instant transitions to `LAPSED`, and each of that billboard's leases
    currently in `ACTIVE` status cascades to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/registration_lapse_lease_suspend_depth2
    """
    parcel, operator, bb, lease = create_registered_billboard_with_lease(
        api, start_date="2026-06-01T00:00:00Z", end_date="2027-06-01T00:00:00Z")
    set_clock(api, "2027-05-15T00:00:00Z")
    fetched = get_billboard(api, bb["id"])
    assert fetched["registration_status"] == "LAPSED"


def test_lapse_suspends_active_lease(api):
    """PRD §2.5: "Any `REGISTERED` billboard whose `registration_expires_at` is at or
    before the new instant transitions to `LAPSED`, and each of that billboard's leases
    currently in `ACTIVE` status cascades to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/registration_lapse_lease_suspend_depth2
    """
    parcel, operator, bb, lease = create_registered_billboard_with_lease(
        api, start_date="2026-06-01T00:00:00Z", end_date="2027-06-01T00:00:00Z")
    set_clock(api, "2027-05-15T00:00:00Z")
    fetched = validate_success(api.get_lease(lease["id"], make_planner_headers()))
    assert fetched["status"] == "SUSPENDED"


# ── Priority: referential (7) beats constraint (9) on lease — Difficulty ──────
def test_lease_on_lapsed_billboard_with_overlap_reports_not_registered(api):
    """PRD §2.8: "a referenced entity must be in the required state: an application must
    be `APPROVED` for permit issuance (`ERR_APPLICATION_NOT_APPROVED`), a billboard must
    be `REGISTERED` for a lease (`ERR_BILLBOARD_NOT_REGISTERED`), and a permit must be
    `ACTIVE` for inspection scheduling (`ERR_PERMIT_INACTIVE`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_lease
    """
    parcel, operator, bb, lease = create_registered_billboard_with_lease(
        api, start_date="2026-06-01T00:00:00Z", end_date="2026-07-01T00:00:00Z")
    set_clock(api, "2027-05-15T00:00:00Z")
    current = get_billboard(api, bb["id"])
    resp = api.create_lease(
        {"billboard_id": bb["id"], "lessee_name": "Second Buyer",
         "start_date": "2026-06-10T00:00:00Z", "end_date": "2026-06-20T00:00:00Z",
         "expected_billboard_version": current["version"]},
        make_applicant_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BILLBOARD_NOT_REGISTERED)


def test_lease_on_lapsed_billboard_without_overlap_reports_not_registered(api):
    """PRD §3.8: "The billboard must be `REGISTERED`, else `ERR_BILLBOARD_NOT_REGISTERED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_lease
    """
    parcel, operator, bb, lease = create_registered_billboard_with_lease(
        api, start_date="2026-06-01T00:00:00Z", end_date="2026-07-01T00:00:00Z")
    set_clock(api, "2027-05-15T00:00:00Z")
    current = get_billboard(api, bb["id"])
    resp = api.create_lease(
        {"billboard_id": bb["id"], "lessee_name": "Later Buyer",
         "start_date": "2026-09-01T00:00:00Z", "end_date": "2026-10-01T00:00:00Z",
         "expected_billboard_version": current["version"]},
        make_applicant_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BILLBOARD_NOT_REGISTERED)


# ── Half-open lease interval overlap (Difficulty) ────────────────────────────
def test_interior_overlapping_lease_rejected(api):
    """PRD §3.8: "a new lease may not overlap any existing non-terminal lease on the same
    billboard, where overlap is judged on the half-open interval so two leases that
    merely abut (one ending exactly when the next begins) are allowed; an overlap is
    refused with `ERR_LEASE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_half_open_interior_overlap_rejected
    """
    parcel, operator, bb, lease = create_registered_billboard_with_lease(
        api, start_date="2026-06-01T00:00:00Z", end_date="2026-07-01T00:00:00Z")
    resp = api.create_lease(
        {"billboard_id": bb["id"], "lessee_name": "Buyer Two",
         "start_date": "2026-06-10T00:00:00Z", "end_date": "2026-06-20T00:00:00Z",
         "expected_billboard_version": bb["version"]},
        make_applicant_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEASE_OVERLAP)


def test_adjacent_lease_allowed(api):
    """PRD §3.8: "a new lease may not overlap any existing non-terminal lease on the same
    billboard, where overlap is judged on the half-open interval so two leases that
    merely abut (one ending exactly when the next begins) are allowed".

    Design: Difficulty/resource_temporal_overlap/lease_half_open_interior_overlap_rejected
    """
    parcel, operator, bb, lease = create_registered_billboard_with_lease(
        api, start_date="2026-06-01T00:00:00Z", end_date="2026-07-01T00:00:00Z")
    adjacent = create_lease(api, bb["id"], operator["id"], "2026-07-01T00:00:00Z",
                            "2026-08-01T00:00:00Z", bb["version"], lessee_name="Adjacent Buyer")
    assert adjacent["status"] == "ACTIVE"


# ── Zero-length / inverted lease interval (Difficulty) ───────────────────────
def test_zero_length_lease_interval_rejected(api):
    """PRD §3.8: "the `start_date` is inclusive and the `end_date` is exclusive — and
    `end_date` must be strictly after `start_date`, else `ERR_INVALID_INTERVAL`."

    Design: Difficulty/boundary_precision_check/zero_length_lease_interval_rejected
    """
    parcel, operator, bb = create_registered_billboard(api)
    resp = api.create_lease(
        {"billboard_id": bb["id"], "lessee_name": "NoTime",
         "start_date": "2026-06-01T00:00:00Z", "end_date": "2026-06-01T00:00:00Z",
         "expected_billboard_version": bb["version"]},
        make_applicant_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL)


def test_inverted_lease_interval_rejected(api):
    """PRD §3.8: "the `start_date` is inclusive and the `end_date` is exclusive — and
    `end_date` must be strictly after `start_date`, else `ERR_INVALID_INTERVAL`."

    Design: Difficulty/boundary_precision_check/zero_length_lease_interval_rejected
    """
    parcel, operator, bb = create_registered_billboard(api)
    resp = api.create_lease(
        {"billboard_id": bb["id"], "lessee_name": "Backwards",
         "start_date": "2026-07-01T00:00:00Z", "end_date": "2026-06-01T00:00:00Z",
         "expected_billboard_version": bb["version"]},
        make_applicant_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL)


# ── OCC on lease create (Corner) ─────────────────────────────────────────────
def test_lease_create_with_stale_billboard_version_rejected(api):
    """PRD §2.6: "If another lease that occupies part of the calendar, or a registration
    renewal, has advanced the billboard's `version` since the client's read, the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's availability
    view is stale."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_billboard_version_on_lease_create
    """
    parcel, operator, bb = create_registered_billboard(api)
    stale_version = bb["version"]
    # First lease legitimately advances the billboard version.
    create_lease(api, bb["id"], operator["id"], "2026-06-01T00:00:00Z",
                 "2026-07-01T00:00:00Z", stale_version)
    # Second lease reuses the pre-first-lease version even though [2026-08,2026-09) is free.
    resp = api.create_lease(
        {"billboard_id": bb["id"], "lessee_name": "Buyer Two",
         "start_date": "2026-08-01T00:00:00Z", "end_date": "2026-09-01T00:00:00Z",
         "expected_billboard_version": stale_version},
        make_applicant_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ── Existence & list-by-FK (Corner) ──────────────────────────────────────────
def test_register_unknown_billboard_not_found(api):
    """PRD §2.8: "for endpoints keyed on a typed root, a missing root yields the specific
    code `ERR_APPLICATION_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, or
    `ERR_BILLBOARD_NOT_FOUND`."

    Design: Corner/entities/register_billboard_not_found
    """
    resp = api.register_billboard(
        NON_EXISTENT_UUID, {"amount_cents": 3333}, make_applicant_headers("op-x"))
    validate_error(resp, ApiErrorId.ERR_BILLBOARD_NOT_FOUND)


def test_list_leases_filtered_by_billboard(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the total
    number of records matching the filter, before pagination), and `has_more` (a boolean
    that is true when records remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/list_billboard_leases_by_billboard_fk
    """
    parcel, operator, bb, lease = create_registered_billboard_with_lease(api)
    resp = api.list_leases(make_planner_headers(), params={"billboard_id": bb["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == lease["id"]
