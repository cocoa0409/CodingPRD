"""Sites, safety holds and the patient roster."""

from test_helpers import (
    ApiErrorId,
    assert_site,
    assert_site_hold,
    build_patient,
    build_portable_unit,
    build_program_period,
    build_site,
    build_site_visit,
    build_staff,
    is_valid_uuid,
    make_guardian_headers,
    make_program_admin_headers,
    make_site_coordinator_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers()


def test_site_registration_applies_declared_defaults(api):
    """PRD §3.1: "A new site opens in `status` `ACTIVE` with `active_hold_count` at zero."
    PRD §3.1: "`roster_disclosure_level`, defaulting to `SUMMARY_ONLY` and settable to
    `CLINICAL_DETAIL`, which decides how much per-child or per-resident detail a facility
    roster report may expose"
    PRD §2.4: "`version` is an integer that starts at 1 on creation and counts the mutations
    the row has absorbed."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix and no embedded meaning;
    clients never supply it."

    Design: Corner/entities/site_creation_applies_declared_defaults_and_starts_at_version_one
    """
    set_clock("2026-05-11T09:00:00Z")
    resp = api.create_site(
        {"name": "Lincoln Elementary", "site_type": "SCHOOL", "state_code": "CA"}, ADMIN
    )
    site = validate_success(resp, 201)
    assert_site(site)
    assert site["status"] == "ACTIVE", f"Expected ACTIVE, got {site['status']}"
    assert site["roster_disclosure_level"] == "SUMMARY_ONLY"
    assert site["active_hold_count"] == 0
    assert site["version"] == 1
    assert is_valid_uuid(site["id"]) and not site["id"].startswith("site")


def test_reading_a_patient_by_unknown_uuid_returns_not_found(api):
    """PRD §2.6: "**Rung 3 — `ERR_NOT_FOUND` (404).** Every identifier resolves to an
    existing row."

    Design: Corner/entities/patient_get_with_unknown_uuid_returns_not_found
    """
    build_site()
    resp = api.get_patient("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_patient_list_pagination_reports_total_count_and_has_more(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters *before* the
    page window is applied, and `has_more` is true exactly when rows remain beyond the current
    window."

    Design: Corner/entities/patients_list_pagination_reports_total_count_and_has_more
    """
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    build_patient(site["id"], coord, external_ref="S-001", first_name="Mia", last_name="Lopez")
    build_patient(site["id"], coord, external_ref="S-002", first_name="Noah", last_name="Park",
                  date_of_birth="2015-11-20", household_size=3)
    build_patient(site["id"], coord, external_ref="S-003", first_name="Ivy", last_name="Chen",
                  date_of_birth="2017-01-09", household_size=5)

    first = api.list_patients(ADMIN, params={"site_id": site["id"], "limit": 2, "offset": 0})
    rows, meta = validate_paginated(first)
    assert len(rows) == 2, f"Expected 2 rows on the first page, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert first.json()["response_type"] == "array"

    second = api.list_patients(ADMIN, params={"site_id": site["id"], "limit": 2, "offset": 2})
    rows2, meta2 = validate_paginated(second)
    assert len(rows2) == 1, f"Expected 1 row on the second page, got {len(rows2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert second.json()["response_type"] == "array"


def test_opening_a_hold_blocks_the_visit_and_releasing_it_restores_the_visit(api):
    """PRD §3.1: "Link one takes the site from `ACTIVE` to `SUSPENDED` and raises its
    `active_hold_count` by one"
    PRD §3.1: "every such visit moves to `HOLD_BLOCKED`, and the number of visits moved is
    recorded on the hold as `blocked_visit_count`."
    PRD §3.1: "The hold moves to `hold_status` `RELEASED` with `released_at` stamped, and the
    site's `active_hold_count` drops by one."
    PRD §3.1: "Every visit sitting in `HOLD_BLOCKED` for which no remaining `ACTIVE` hold on
    the site still intersects its window returns to `SCHEDULED`"

    Design: Corner/state_machines/site_hold_cascade_blocks_the_visit_and_release_restores_it
    """
    set_clock("2026-05-11T08:00:00Z")
    period = build_program_period()
    site = build_site(site_type="SNF", roster_disclosure_level="CLINICAL_DETAIL")
    coord = make_site_coordinator_headers(site["id"])
    dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    unit = build_portable_unit()
    visit = build_site_visit(
        site["id"], period["id"], unit["id"], dentist["id"], coord,
        onsite_dentist_staff_id=dentist["id"],
    )

    hold_resp = api.create_site_hold(
        {
            "site_id": site["id"],
            "hold_type": "OUTBREAK_LOCKDOWN",
            "starts_at": "2026-05-11T00:00:00Z",
            "ends_at": "2026-05-18T00:00:00Z",
            "reason": "Norovirus outbreak on unit 2",
        },
        ADMIN,
    )
    hold = validate_success(hold_resp, 201)
    assert_site_hold(hold)
    assert hold["blocked_visit_count"] == 1

    site_now = validate_success(api.get_site(site["id"], ADMIN))
    assert site_now["status"] == "SUSPENDED"
    assert site_now["active_hold_count"] == 1
    visit_now = validate_success(api.get_site_visit(visit["id"], ADMIN))
    assert visit_now["status"] == "HOLD_BLOCKED"

    released = validate_success(api.release_site_hold(hold["id"], ADMIN))
    assert released["hold_status"] == "RELEASED"
    site_after = validate_success(api.get_site(site["id"], ADMIN))
    assert site_after["status"] == "ACTIVE"
    assert site_after["active_hold_count"] == 0
    visit_after = validate_success(api.get_site_visit(visit["id"], ADMIN))
    assert visit_after["status"] == "SCHEDULED"


def test_scheduling_at_a_suspended_site_is_refused_even_outside_the_hold_window(api):
    """PRD §2.6: "**Rung 10 — `ERR_SITE_ON_HOLD` (409) — the site hold gate.** Detailed in
    §2.7. A write that schedules, reschedules, starts or registers against a site visit is
    refused when the visit's site is `SUSPENDED`, or when the visit's own scheduled window
    intersects any `ACTIVE` hold on that site."

    Design: Corner/state_machines/creating_a_visit_at_a_suspended_site_returns_site_on_hold
    """
    set_clock("2026-05-11T08:00:00Z")
    period = build_program_period()
    site = build_site(site_type="SNF", roster_disclosure_level="CLINICAL_DETAIL")
    coord = make_site_coordinator_headers(site["id"])
    dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    unit = build_portable_unit()
    validate_success(
        api.create_site_hold(
            {
                "site_id": site["id"],
                "hold_type": "OUTBREAK_LOCKDOWN",
                "starts_at": "2026-05-11T00:00:00Z",
                "ends_at": "2026-05-18T00:00:00Z",
                "reason": "Norovirus outbreak",
            },
            ADMIN,
        ),
        201,
    )

    resp = api.create_site_visit(
        {
            "site_id": site["id"],
            "program_period_id": period["id"],
            "portable_unit_id": unit["id"],
            "lead_staff_id": dentist["id"],
            "onsite_dentist_staff_id": dentist["id"],
            "scheduled_start_at": "2026-06-02T09:00:00Z",
            "scheduled_end_at": "2026-06-02T15:00:00Z",
            "chair_count": 2,
        },
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_SITE_ON_HOLD.value, 409)

    rows, _ = validate_paginated(api.list_site_visits(ADMIN, params={"site_id": site["id"]}))
    assert rows == [], f"No visit may have been created, got {len(rows)}"
    assert validate_success(api.get_site(site["id"], ADMIN))["status"] == "SUSPENDED"


def test_request_without_identity_headers_is_refused_at_the_first_rung(api):
    """PRD §2.6: "**Rung 1 — `ERR_UNAUTHENTICATED` (401).** Both `X-User-ID` and
    `X-User-Role` are present, and `X-User-Role` names one of the seven declared roles.
    Applies to every endpoint including reads and the clock control."

    Design: Corner/validations/missing_user_headers_returns_unauthenticated
    """
    site = build_site()
    resp = api.get_raw(f"/mobile-dentistry/sites/{site['id']}", headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_guardian_cannot_add_a_patient_to_the_roster(api):
    """PRD §2.1: "A `Guardian`'s entire authorised surface is the single-report read, and
    every other endpoint refuses a `Guardian` with `ERR_UNAUTHORIZED`."

    Design: Corner/validations/guardian_cannot_create_a_patient_returns_unauthorized
    """
    site = build_site()
    resp = api.create_patient(
        {
            "site_id": site["id"],
            "patient_type": "STUDENT",
            "external_ref": "S-001",
            "first_name": "Mia",
            "last_name": "Lopez",
            "date_of_birth": "2016-03-04",
            "household_size": 4,
        },
        make_guardian_headers("guardian-user-001"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    rows, _ = validate_paginated(api.list_patients(ADMIN, params={"site_id": site["id"]}))
    assert rows == [], "A refused create must leave no Patient row behind"
