"""Onboarding, listing, and access control: schedule generation over an empty
window, client-creation defaults, structural/enum/existence validation, list
pagination and FK-reverse retrieval, and the authentication/authorization gates."""
from test_helpers import (
    setup_active_schedule,
    create_client,
    create_caregiver,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_caregiver_headers,
    create_client_payload,
    create_visit_payload,
    create_family_contact_payload,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


class TestGenerateVisitsEmptyWindow:
    def _schedule(self, api):
        return setup_active_schedule(
            api,
            schedule_overrides={
                "task_type": "GROCERY", "frequency": "WEEKLY", "day_of_week": "MON",
                "start_time": "09:00", "duration_minutes": 120,
                "start_date": "2026-03-01T00:00:00Z", "end_date": "2026-03-31T00:00:00Z",
            },
        )

    def test_no_matching_day_returns_empty_array(self, api):
        """PRD §3.3: "The system creates one SCHEDULED Visit for each date within
        that window that matches the schedule's day_of_week occurrence pattern; when
        the window contains no matching day, the result is an empty array."

        Design: Difficulty/boundary_precision_check/generate_visits_empty_window_returns_empty
        """
        ctx = self._schedule(api)
        # Window covers only Thursday 2026-03-05, but the schedule lands on MON.
        data = get_success_data(
            api.generate_visits(ctx["schedule"]["id"], {"from_date": "2026-03-05T00:00:00Z", "to_date": "2026-03-05T23:59:59Z"}, COORD)
        )
        assert data == [], f"expected an empty Visit array, got {data}"

    def test_empty_generation_leaves_schedule_active(self, api):
        """PRD §3.3: "A schedule begins ACTIVE; it can be moved to PAUSED by the
        client-suspension cascade (§2.8), and it reaches the terminal ENDED state once
        the clock passes its end_date with no remaining occurrences."

        Design: Difficulty/boundary_precision_check/generate_visits_empty_window_returns_empty
        """
        ctx = self._schedule(api)
        api.generate_visits(ctx["schedule"]["id"], {"from_date": "2026-03-05T00:00:00Z", "to_date": "2026-03-05T23:59:59Z"}, COORD)
        schedule = validate_success(api.get_schedule(ctx["schedule"]["id"], COORD))
        assert schedule["status"] == "ACTIVE", f"schedule must remain ACTIVE, got {schedule['status']}"


def test_create_client_defaults_to_active_zero_balance(api):
    """PRD §3.1: "A new client begins in ACTIVE status with
    outstanding_balance_cents initialized to 0."

    Design: Corner/entities/create_client_returns_201_with_defaults
    """
    client = validate_success(api.create_client(create_client_payload(name="Client Z"), COORD), 201)
    assert client["status"] == "ACTIVE", f"expected ACTIVE, got {client['status']}"
    assert client["outstanding_balance_cents"] == 0, f"expected balance 0, got {client['outstanding_balance_cents']}"


def test_get_unknown_client_returns_not_found(api):
    """PRD §2.9: "The system validates the existence of every resource named in a
    path from left to right, and rejects the request with ERR_RESOURCE_NOT_FOUND at
    the first path segment whose identifier does not correspond to an existing
    resource."

    Design: Corner/entities/error_client_not_found_on_get
    """
    resp = api.get_client(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_create_visit_missing_required_field_rejected(api):
    """PRD §2.10: "Structural validity of the request body — required fields present
    with correct types — is fifth, yielding ERR_INVALID_REQUEST"

    Design: Corner/entities/error_required_field_missing_on_create_visit
    """
    client = create_client(api)
    resp = api.create_visit(
        {"client_id": client["id"], "task_type": "COMPANION", "scheduled_start": "2026-03-05T09:00:00Z"}, COORD
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_visit_invalid_task_type_enum_rejected(api):
    """PRD §2.10: "enum-typed fields carrying an undeclared member are sixth,
    yielding ERR_INVALID_ENUM."

    Design: Corner/entities/error_invalid_enum_task_type_on_create_visit
    """
    client = create_client(api)
    resp = api.create_visit(
        create_visit_payload(client["id"], task_type="MASSAGE",
                             scheduled_start="2026-03-05T09:00:00Z", scheduled_end="2026-03-05T10:00:00Z"),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_create_visit_inverted_time_range_rejected(api):
    """PRD §3.4: "A visit's scheduled_end must be strictly after its scheduled_start,
    or creation is rejected with ERR_INVALID_TIME_RANGE."

    Design: Corner/validations/error_invalid_time_range_visit_create
    """
    client = create_client(api)
    resp = api.create_visit(
        create_visit_payload(client["id"], scheduled_start="2026-03-05T12:00:00Z", scheduled_end="2026-03-05T11:00:00Z"),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


def test_visits_list_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/endpoints/visits_list_pagination_shape
    """
    client = create_client(api)
    validate_success(api.create_visit(create_visit_payload(client["id"], scheduled_start="2026-03-05T09:00:00Z", scheduled_end="2026-03-05T10:00:00Z"), COORD), 201)
    validate_success(api.create_visit(create_visit_payload(client["id"], task_type="GROCERY", scheduled_start="2026-03-05T11:00:00Z", scheduled_end="2026-03-05T12:00:00Z"), COORD), 201)
    data, meta = validate_paginated(api.list_visits(COORD, params={"client_id": client["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


def test_family_contacts_listed_under_client(api):
    """PRD §3.1: "Each FamilyContact is created against the client with a name, an
    email, and a stated relationship to the senior (for example, daughter or son),
    and is bound to that client through its client_id. Contacts may be listed back
    for a client."

    Design: Corner/endpoints/fk_reverse_family_contacts_listed_under_client
    """
    client = create_client(api)
    validate_success(
        api.create_family_contact(client["id"], create_family_contact_payload(name="Jane Doe", email="jane@x.com", relationship="daughter"), COORD), 201
    )
    data, meta = validate_paginated(api.list_family_contacts(client["id"], COORD))
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"


def test_request_without_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    resp = api.create_client(create_client_payload(name="NoAuth"), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_caregiver_role_cannot_create_client(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to invoke the target endpoint, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/errors/error_unauthorized_caregiver_creates_client
    """
    cg = create_caregiver(api, name="CG Auth")
    resp = api.create_client(create_client_payload(name="Sneaky"), make_caregiver_headers(cg["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
