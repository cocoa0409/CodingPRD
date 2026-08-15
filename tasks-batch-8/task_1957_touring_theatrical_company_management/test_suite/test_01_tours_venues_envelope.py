"""Tours, venues, and the response envelope (PRD §2.2, §3.1)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PRODUCER,
    TOUR_MANAGER,
    assert_budget_identity,
    assert_tour,
    assert_venue,
    create_tour,
    create_tour_payload,
    create_venue,
    create_venue_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)


def test_tour_create_defaults_and_roundtrip(api):
    """PRD §3.1: "A new tour starts in `PLANNING` status with `recouped` false and
    all computed counters — `budget_committed_cents`, `budget_spent_cents`,
    `cumulative_producer_net_cents`, `royalty_accrued_cents` — at zero."
    PRD §3.1: "The `budget_available_cents` of a tour is always its
    `budget_total_cents` minus `budget_committed_cents` minus
    `budget_spent_cents`; this identity holds after every mutation, and every
    mutation that moves money between the committed and spent buckets preserves it."

    Design: Corner/entities/tour_create_defaults_and_roundtrip
    """
    created = validate_success(api.create_tour(create_tour_payload(), PRODUCER), 201)
    assert_tour(created)
    assert created["status"] == "PLANNING"
    assert created["recouped"] is False
    assert created["budget_committed_cents"] == 0
    assert created["budget_spent_cents"] == 0
    assert created["cumulative_producer_net_cents"] == 0
    assert created["royalty_accrued_cents"] == 0
    assert created["budget_available_cents"] == created["budget_total_cents"]

    fetched = validate_success(api.get_tour(created["id"], PRODUCER), 200)
    assert_tour(fetched)
    assert fetched == created, "GET round-trip must return identical field values"
    assert_budget_identity(fetched)


def test_tour_create_missing_required_returns_invalid_request(api):
    """PRD §3.1: "A production begins when a `Producer` creates a tour, supplying
    its `name`, the total operating budget `budget_total_cents`, the
    `capitalization_cents` the production must earn back before post-recoupment
    royalty rates apply, the per-diem policy `per_diem_policy` (either `FULL_WEEK`
    or `ACTUAL_DAYS`), the daily per-diem rate `per_diem_daily_cents` (which must
    be greater than zero), and the royalty bracket boundary
    `royalty_tier_threshold_cents` (also greater than zero)."
    PRD §2.8: "Third comes request shape (priority 4): required fields present,
    unknown fields rejected, enums valid, and numeric ranges respected"

    Design: Corner/entities/tour_create_missing_required_returns_invalid_request
    """
    payload = create_tour_payload()
    del payload["royalty_tier_threshold_cents"]
    resp = api.create_tour(payload, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_tour_create_invalid_enum_rejected(api):
    """PRD §3.1: "the per-diem policy `per_diem_policy` (either `FULL_WEEK` or
    `ACTUAL_DAYS`)"
    PRD §2.8: "Third comes request shape (priority 4): required fields present,
    unknown fields rejected, enums valid, and numeric ranges respected"

    Design: Corner/entities/tour_create_invalid_enum_rejected
    """
    payload = create_tour_payload(per_diem_policy="WEEKLY")
    resp = api.create_tour(payload, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_tour_create_computed_field_input_rejected(api):
    """PRD §2.10: "A tour’s `budget_committed_cents`, `budget_spent_cents`, `budget_available_cents`, `cumulative_producer_net_cents`, `recouped`, and `royalty_accrued_cents` are computed fields maintained by the server."
    PRD §2.8: "Third comes request shape (priority 4): required fields present,
    unknown fields rejected, enums valid, and numeric ranges respected"

    Design: Corner/entities/tour_create_computed_field_input_rejected
    """
    payload = create_tour_payload(budget_committed_cents=999)
    resp = api.create_tour(payload, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_entity_not_found_returns_404(api):
    """PRD §2.7: "The first identifier that fails to resolve, or whose resource
    does not belong to the established parent, rejects the request with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp1 = api.get_stop(NON_EXISTENT_UUID, PRODUCER)
    validate_error(resp1, ApiErrorId.ERR_NOT_FOUND)

    resp2 = api.put_tech_check(NON_EXISTENT_UUID, {"actual_value": 5}, TOUR_MANAGER)
    validate_error(resp2, ApiErrorId.ERR_NOT_FOUND)


def test_venue_create_and_get(api):
    """PRD §3.1: "A `Producer` registers each venue with its `name`, `city`, and
    the four technical specifications the rider will later be checked against:
    `stage_width_ft` and `power_amps` (each greater than zero),
    `fly_capacity_lines`, and `crew_available` — the number of local stagehands
    the venue can supply per call (each non-negative)."

    Design: Corner/endpoints/venue_create_and_get
    """
    created = validate_success(api.create_venue(create_venue_payload(), PRODUCER), 201)
    assert_venue(created)

    fetched = validate_success(api.get_venue(created["id"], TOUR_MANAGER), 200)
    assert_venue(fetched)
    assert fetched["stage_width_ft"] == 44
    assert fetched["crew_available"] == 20
    assert fetched["name"] == "Venue V"
    assert fetched["city"] == "Chicago"


def test_envelope_on_success_and_error(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/envelope_on_success_and_error
    """
    tour = create_tour()

    ok = api.get_tour(tour["id"], PRODUCER)
    body = ok.json()
    assert ok.status_code == 200
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["data"]["id"] == tour["id"]

    err = api.get_stop(NON_EXISTENT_UUID, PRODUCER)
    err_body = err.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()
    validate_error(err, ApiErrorId.ERR_NOT_FOUND)
