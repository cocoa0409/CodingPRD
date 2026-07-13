"""Onboarding and title-creation compliance tests."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    admin_headers, make_author_headers,
    create_title_payload, create_narrator_payload,
    assert_title, assert_narrator,
    onboard_author,
)


def test_create_title_defaults(api):
    """PRD §3.1: "A new title is born in `DRAFT` status with `rights_status` of
    `ACTIVE`."
    PRD §3.1: "Its `finished_hours` is 0 until a full deliverable is approved,
    and its `retail_sample_start_sec` and `retail_sample_end_sec` are both unset
    until a sample window is chosen."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments
    by exactly 1 on every mutation that changes the resource."

    Design: Corner/entities/create_title_returns_created_with_system_fields
    """
    author = onboard_author(api)
    resp = api.create_title(create_title_payload(), make_author_headers(author["id"]))
    data = validate_success(resp, 201)
    assert_title(data)
    assert data["status"] == "DRAFT"
    assert data["rights_status"] == "ACTIVE"
    assert data["finished_hours"] == 0
    assert data["version"] == 1


def test_get_missing_title_returns_not_found(api):
    """PRD §2.6: "a missing `title_id` yields `ERR_TITLE_NOT_FOUND`".

    Design: Corner/entities/get_nonexistent_title_returns_not_found
    """
    resp = api.get_title("00000000-0000-4000-8000-000000000000", admin_headers())
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_FOUND.value)


def test_new_narrator_computed_defaults(api):
    """PRD §3.1: "A narrator likewise starts with a `payout_balance_cents` of 0
    and an `active_booked_days` of 0; both are computed running totals maintained
    by the system rather than client inputs."

    Design: Corner/entities/narrator_active_booked_days_defaults_zero
    """
    resp = api.create_narrator(create_narrator_payload(hourly_rate_cents=15000), admin_headers())
    data = validate_success(resp, 201)
    assert_narrator(data)
    assert data["active_booked_days"] == 0
    assert data["payout_balance_cents"] == 0


def test_title_version_increments_on_open(api):
    """PRD §2.4: "an integer `version` that starts at 1 on creation and increments
    by exactly 1 on every mutation that changes the resource."
    PRD §3.1: "Once a draft is ready to receive narrators, the owning author opens
    it, advancing the title `DRAFT → OPEN_FOR_AUDITION`."

    Design: Corner/cross_cutting_complexity_layers/title_version_increments_on_open
    """
    author = onboard_author(api)
    created = validate_success(api.create_title(create_title_payload(), make_author_headers(author["id"])), 201)
    opened = validate_success(api.open_title(created["id"], make_author_headers(author["id"])), 200)
    assert created["version"] == 1
    assert opened["version"] == 2
