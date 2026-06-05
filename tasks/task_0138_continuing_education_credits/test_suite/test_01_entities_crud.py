"""Entity CRUD: creation, defaults, not-found, required/type validation,
immutability, system-snapshotted fields, FK integrity, and listing.

Each test translates exactly one Corner/entities instance.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    assert_license_board,
    assert_completion,
    factories as F,
    fixtures as FX,
)

ADMIN = FX.ADMIN


def test_create_license_board_returns_201_with_fields(api):
    """PRD §3.1: "A `BoardAdmin` establishes a license board by supplying its
    `name`, a two-letter uppercase `jurisdiction_code` (for example, "CA"), and
    the `credit_unit` it accredits — one of `CEU`, `CME`, or `CLE`."
    PRD §2.4: "Most entities also carry an integer `version` that starts at its
    initial value and increments by one on each mutation that changes the resource."

    Design: Corner/entities/create_license_board_returns_201_with_fields
    """
    FX.set_clock("2026-01-01T00:00:00Z")
    payload = F.create_license_board_payload(
        name="CA Board", jurisdiction_code="CA", credit_unit="CLE",
        cycle_length_months=24, total_required_hours=30.0)
    # Only the required + chosen fields; defaults exercised in a sibling test.
    payload.pop("carryover_cap_hours", None)
    payload.pop("audit_cooldown_days", None)
    payload.pop("reminder_lead_days", None)

    resp = api.create_license_board(payload, ADMIN)
    data = validate_success(resp, 201)

    assert data["jurisdiction_code"] == "CA"
    assert data["credit_unit"] == "CLE"
    assert float(data["total_required_hours"]) == 30.0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert_license_board(data)


def test_board_default_carryover_cap_applied_when_omitted(api):
    """PRD §3.1: "The `carryover_cap_hours` caps how much verified surplus may
    roll into the next cycle and defaults to 10.0 when omitted; the
    `audit_cooldown_days` sets the minimum number of days that must elapse
    between the close of one audit and the start of the next on the same
    licensee, defaulting to 365; and the `reminder_lead_days` sets how many days
    before a deadline the reminder begins, defaulting to 60."

    Design: Corner/entities/board_default_carryover_cap_applied_when_omitted
    """
    FX.set_clock("2026-01-01T00:00:00Z")
    payload = {
        "name": "CA Board", "jurisdiction_code": "CA", "credit_unit": "CLE",
        "cycle_length_months": 24, "total_required_hours": 30.0,
    }
    data = validate_success(api.create_license_board(payload, ADMIN), 201)

    assert float(data["carryover_cap_hours"]) == 10.0
    assert int(data["audit_cooldown_days"]) == 365
    assert int(data["reminder_lead_days"]) == 60


def test_get_board_not_found_returns_404(api):
    """PRD §2.9: "Any referenced resource — whether named in the path or in the
    request body — that does not exist yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_board_not_found_returns_404
    """
    FX.set_clock("2026-01-01T00:00:00Z")
    resp = api.get_license_board("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_course_missing_required_field_returns_invalid_request(api):
    """PRD §2.10: "Malformed bodies (a missing required field, a bad enum value,
    or a non-positive credit-hour value) are rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/create_course_missing_required_field_returns_invalid_request
    """
    board = FX.create_board(with_requirements=False)
    provider = FX.create_accredited_provider(board["id"])

    # No credit_hours field at all.
    payload = {"provider_id": provider["id"], "title": "E", "category": "ETHICS"}
    resp = api.create_course(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_course_non_positive_credit_hours_returns_invalid_request(api):
    """PRD §3.1: "A course is created under a provider ... with a `title`, a
    `category` (`ETHICS`, `SUBSTANCE`, or `GENERAL`), and `credit_hours` awarded
    on verified completion (strictly greater than 0, one decimal place)."
    PRD §2.10: "Malformed bodies (a missing required field, a bad enum value, or
    a non-positive credit-hour value) are rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/create_course_non_positive_credit_hours_returns_invalid_request
    """
    board = FX.create_board(with_requirements=False)
    provider = FX.create_accredited_provider(board["id"])

    payload = F.create_course_payload(provider["id"], "ETHICS", 0.0, title="E0")
    resp = api.create_course(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_requirement_min_hours_sum_exceeds_board_total_returns_range(api):
    """PRD §3.1: "There is an aggregate ceiling: the sum of `min_hours` across
    all of a board's non-`GENERAL` requirements must not exceed that board's
    `total_required_hours`. A request that would breach this ceiling is rejected
    with `ERR_VALIDATION_RANGE`."

    Design: Corner/entities/requirement_min_hours_sum_exceeds_board_total_returns_range
    """
    FX.set_clock("2026-01-01T00:00:00Z")
    board = get_success_data(api.create_license_board(
        F.create_license_board_payload(
            name="Small Board", jurisdiction_code="TX", credit_unit="CME",
            total_required_hours=5.0), ADMIN))
    get_success_data(api.create_requirement(
        board["id"], F.create_requirement_payload("ETHICS", 4.0), ADMIN))

    # 4.0 + 3.0 > 5.0 board total.
    resp = api.create_requirement(
        board["id"], F.create_requirement_payload("SUBSTANCE", 3.0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_RANGE.value, 422)


def test_certificate_is_immutable_no_version_field(api):
    """PRD §2.4: "Two entities are deliberately lightweight and carry only `id`
    and `created_at` — they have neither `updated_at` nor `version`, because they
    are immutable once written: the `Certificate` and the `Attestation`."
    PRD §3.8: "snapshots the cycle's `final_earned_hours` at issuance into
    `total_hours_certified`, and records its `issued_at` timestamp."

    Design: Corner/entities/certificate_is_immutable_no_version_field
    """
    met = FX.setup_requirements_met_cycle()
    cycle, licensee = met["cycle"], met["licensee"]
    from test_helpers import make_licensee_headers
    lic_headers = make_licensee_headers(licensee["id"])

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], lic_headers))
    get_success_data(api.renew_cycle(
        cycle["id"], F.renew_cycle_payload(cyc["version"]), lic_headers))

    data, meta = validate_paginated(api.list_cycle_certificates(cycle["id"], lic_headers))
    assert len(data) == 1, "exactly one certificate issued on renew"
    cert = data[0]
    assert "serial_number" in cert and isinstance(cert["serial_number"], str)
    assert float(cert["total_hours_certified"]) == 30.0
    assert "version" not in cert, "certificate is immutable; no version field"
    assert "updated_at" not in cert, "certificate is immutable; no updated_at field"


def test_completion_awarded_hours_snapshotted_not_client_supplied(api):
    """PRD §3.4: "At submission the system snapshots the course's award onto the
    completion: `awarded_hours` is copied from the course's `credit_hours` and
    `category` is copied from the course's `category`, and these snapshots are
    immune to any later edits to the course."

    Design: Corner/entities/completion_awarded_hours_snapshotted_not_client_supplied
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "GENERAL", 24.0)

    from test_helpers import make_licensee_headers
    payload = F.create_completion_payload(licensee["id"], course["id"], cycle["id"])
    data = validate_success(
        api.create_completion(payload, make_licensee_headers(licensee["id"])), 201)

    assert float(data["awarded_hours"]) == 24.0, "awarded_hours snapshotted from course"
    assert data["category"] == "GENERAL", "category snapshotted from course"
    assert data["status"] == "PENDING_VERIFICATION"
    assert_completion(data)


def test_completion_with_nonexistent_course_returns_not_found(api):
    """PRD §2.9: "Body-referenced foreign keys are likewise validated for
    existence."
    PRD §2.9: "Any referenced resource — whether named in the path or in the
    request body — that does not exist yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/completion_with_nonexistent_course_returns_not_found
    """
    base = FX.setup_board_provider_licensee_cycle(
        with_requirements=False, with_provider=False)
    licensee, cycle = base["licensee"], base["cycle"]

    from test_helpers import make_licensee_headers
    payload = F.create_completion_payload(
        licensee["id"], "00000000-0000-4000-8000-000000000000", cycle["id"])
    resp = api.create_completion(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_completions_filtered_by_licensee_paginated(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`
    (the total number of matching items irrespective of the page window), and
    `has_more` (true when more items exist beyond the current page) inside `meta`."

    Design: Corner/entities/list_completions_filtered_by_licensee_paginated
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "GENERAL", 24.0)
    FX.log_completion(licensee["id"], course["id"], cycle["id"])

    data, meta = validate_paginated(
        api.list_completions(ADMIN, params={"licensee_id": licensee["id"], "limit": 10, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
