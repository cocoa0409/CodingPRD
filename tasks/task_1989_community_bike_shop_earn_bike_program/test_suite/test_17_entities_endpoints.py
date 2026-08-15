"""Entity-creation corners, listing/pagination/filtering, computed reads, and
the error envelope (queue B)."""
from datetime import datetime, timezone

from test_helpers import (
    api_client, validate_success, validate_paginated,
    make_donor, make_bike, triage_bike, make_participant,
    make_membership, make_volunteer, set_clock,
    TEST_USERS, make_member_headers,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware datetime (format-agnostic).

    PRD §2.4 pins three fractional digits only for created_at/updated_at;
    clock-derived fields such as enrollment_deadline are compared by instant.
    """
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_bike_intake_defaults_and_initial_state():
    """PRD §3.1: "The new bike enters at `RECEIVED` with `condition_grade` and
    `frame_damage` both null, `parts_cost_cents` at 0, and `rework_count` at 0;
    registering the bike also increments the donor's `donated_bike_count`."

    Design: Corner/entities/bike_intake_defaults_and_initial_state
    """
    d = make_donor(display_name="D E", donor_type="INDIVIDUAL", email="de@x.org")
    bike = validate_success(
        api_client.create_bike(
            {"donor_id": d["id"], "serial_number": "SN-E1", "bike_type": "ROAD",
             "wheel_size_inches": 27},
            COORD,
        ),
        expected_status=201,
    )
    assert bike["status"] == "RECEIVED"
    assert bike["condition_grade"] is None
    assert bike["frame_damage"] is None
    assert bike["parts_cost_cents"] == 0
    assert bike["rework_count"] == 0
    assert bike["version"] == 1
    assert bike["latest_inspection_result"] is None
    donor_after = validate_success(api_client.get_donor(d["id"], COORD))
    assert donor_after["donated_bike_count"] == 1


def test_bike_computed_fields_input_ignored():
    """PRD §3.1: "The new bike enters at `RECEIVED` with `condition_grade` and
    `frame_damage` both null, `parts_cost_cents` at 0, and `rework_count` at 0".

    Design: Corner/entities/bike_computed_fields_input_ignored
    """
    d = make_donor(display_name="D CI", donor_type="INDIVIDUAL", email="dci@x.org")
    bike = validate_success(
        api_client.create_bike(
            {"donor_id": d["id"], "serial_number": "SN-CI", "bike_type": "MTB",
             "wheel_size_inches": 29, "status": "SOLD", "parts_cost_cents": 99999},
            COORD,
        ),
        expected_status=201,
    )
    assert bike["status"] == "RECEIVED"
    assert bike["parts_cost_cents"] == 0


def test_participant_required_hours_and_deadline_computed():
    """PRD §3.7: "The record enters at `ENROLLED` with `enrolled_at` stamped
    from the logical clock, an `enrollment_deadline` exactly 90 days after
    enrollment, a `required_hours` of 8 for `YOUTH` and 12 for `ADULT`,
    `hours_earned` at 0, `safety_quiz_passed` false, and no reserved bike." and
    PRD §2.4: "At server startup the clock reads exactly
    2026-08-01T00:00:00Z".

    Design: Corner/entities/participant_required_hours_and_deadline_computed
    """
    py = validate_success(
        api_client.create_participant(
            {"full_name": "P Y", "contact_email": "py@x.org", "age_group": "YOUTH"},
            COORD,
        ),
        expected_status=201,
    )
    pa = validate_success(
        api_client.create_participant(
            {"full_name": "P A", "contact_email": "pa@x.org", "age_group": "ADULT"},
            COORD,
        ),
        expected_status=201,
    )
    assert py["required_hours"] == 8
    assert pa["required_hours"] == 12
    # default clock 2026-08-01T00:00:00Z + 90 days == 2026-10-30T00:00:00Z
    assert _instant(py["enrollment_deadline"]) == _instant("2026-10-30T00:00:00Z")
    assert _instant(pa["enrollment_deadline"]) == _instant("2026-10-30T00:00:00Z")
    for p in (py, pa):
        assert p["status"] == "ENROLLED"
        assert p["hours_earned"] == 0
        assert p["safety_quiz_passed"] is False


def test_volunteer_listing_filter_and_pagination():
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside its `meta` object." and "`limit` controls page size:
    it defaults to 10".

    Design: Corner/entities/volunteer_listing_filter_and_pagination
    """
    v1 = make_volunteer(full_name="V 1", email="v1@x.org")
    v2 = make_volunteer(full_name="V 2", email="v2@x.org")
    v3 = make_volunteer(full_name="V 3", email="v3@x.org")
    validate_success(
        api_client.suspend_volunteer(v2["id"], {"reason": "conduct"}, DIRECTOR)
    )
    data_s, meta_s = validate_paginated(
        api_client.list_volunteers(COORD, params={"engagement_status": "SUSPENDED"})
    )
    assert meta_s["total_count"] == 1
    assert data_s[0]["id"] == v2["id"]
    assert meta_s["limit"] == 10
    assert meta_s["offset"] == 0
    assert meta_s["has_more"] is False

    data_a, meta_a = validate_paginated(
        api_client.list_volunteers(COORD, params={"engagement_status": "ACTIVE"})
    )
    assert meta_a["total_count"] == 2
    assert meta_a["limit"] == 10
    assert meta_a["has_more"] is False


def test_bikes_pagination_interaction():
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside its `meta` object." and "`limit` controls page size:
    it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100.
    `offset` controls how many records are skipped and defaults to 0."

    Design: Corner/endpoints/bikes_pagination_interaction
    """
    d = make_donor(display_name="D PG", donor_type="INDIVIDUAL", email="dpg@x.org")
    for sn, bt, wh in (("SN-P1", "ROAD", 27), ("SN-P2", "MTB", 29), ("SN-P3", "BMX", 20)):
        make_bike(d["id"], serial_number=sn, bike_type=bt, wheel_size_inches=wh)
    data1, meta1 = validate_paginated(
        api_client.list_bikes(COORD, params={"limit": 2})
    )
    assert len(data1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["offset"] == 0

    data2, meta2 = validate_paginated(
        api_client.list_bikes(COORD, params={"limit": 2, "offset": 2})
    )
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    data3, meta3 = validate_paginated(api_client.list_bikes(COORD))
    assert len(data3) == 3
    assert meta3["limit"] == 10
    assert meta3["offset"] == 0
    assert meta3["has_more"] is False


def test_bikes_filter_combination():
    """PRD §2.3: "Unless a filter narrows the result set, list endpoints return
    records sorted by `created_at` in ascending order." and the endpoint
    accepts combined `status`/`bike_type`/`donor_id` filters (PRD §4 GET
    /bikes: "List/filter bikes").

    Design: Corner/endpoints/bikes_filter_combination
    """
    d1 = make_donor(display_name="D F1", donor_type="INDIVIDUAL", email="df1@x.org")
    d2 = make_donor(display_name="D F2", donor_type="ORGANIZATION", email="df2@x.org")
    b1 = make_bike(d1["id"], serial_number="SN-F1", bike_type="ROAD",
                   wheel_size_inches=27)
    triage_bike(b1["id"], "B", False)
    make_bike(d1["id"], serial_number="SN-F2", bike_type="ROAD", wheel_size_inches=27)
    b3 = make_bike(d2["id"], serial_number="SN-F3", bike_type="MTB",
                   wheel_size_inches=26)
    triage_bike(b3["id"], "C", False)

    data1, meta1 = validate_paginated(
        api_client.list_bikes(COORD, params={"status": "TRIAGED", "bike_type": "ROAD"})
    )
    assert meta1["total_count"] == 1
    assert data1[0]["id"] == b1["id"]

    data2, meta2 = validate_paginated(
        api_client.list_bikes(COORD, params={"donor_id": d2["id"]})
    )
    assert meta2["total_count"] == 1
    assert data2[0]["id"] == b3["id"]


def test_receipt_and_billing_computed_reads():
    """PRD §3.14: "The receipt response reports the `donor_id`, the `year`, the
    counted `bike_count`, both totals (`flat_total_cents` and
    `fmv_total_cents`), the donor's `receipt_method`, and the
    `effective_total_cents`" and "The `year` parameter defaults to the clock's
    current year." PRD §3.12: "The billing read reports the `membership_id`,
    the `month`, the `tier`, the `session_count`, and the computed
    `amount_cents`; the `month` parameter defaults to the clock's current
    month." and "Under the `PRO` tier's flat-monthly variant, the bill is 2500
    cents regardless of session count."

    Design: Corner/endpoints/receipt_and_billing_computed_reads
    """
    d = make_donor(display_name="D CR", donor_type="INDIVIDUAL", email="dcr@x.org",
                   receipt_method="FMV_COMPARABLE")
    b = make_bike(d["id"], serial_number="SN-CR", bike_type="KIDS", wheel_size_inches=20)
    triage_bike(b["id"], "A", False)
    receipt = validate_success(api_client.get_donor_receipt(d["id"], DIRECTOR))
    # KIDS/A FMV: round(4000 * 1.0 * 0.6) == 2400; default year = clock year 2026
    assert receipt["year"] == 2026
    assert receipt["receipt_method"] == "FMV_COMPARABLE"
    assert receipt["effective_total_cents"] == 2400
    assert receipt["bike_count"] == 1

    m = make_membership(member_name="M CR", member_email="mcr@x.org", tier="PRO",
                        end_date="2026-12-31")
    billing = validate_success(
        api_client.get_membership_billing(m["id"], make_member_headers(m["id"]))
    )
    assert billing["month"] == "2026-08"
    assert billing["session_count"] == 0
    assert billing["amount_cents"] == 2500
    assert billing["tier"] == "PRO"


def test_receipt_excludes_ungraded_bikes():
    """PRD §3.14: "The input set is the donor's donated bikes whose
    `created_at` falls in the requested calendar year and whose
    `condition_grade` is set — ungraded bikes still in `RECEIVED` are
    excluded."

    Design: Corner/calculations/receipt_excludes_ungraded_bikes
    """
    d = make_donor(display_name="D IU", donor_type="INDIVIDUAL", email="diu@x.org")
    b1 = make_bike(d["id"], serial_number="SN-U1", bike_type="ROAD",
                   wheel_size_inches=27)
    triage_bike(b1["id"], "B", False)
    make_bike(d["id"], serial_number="SN-U2", bike_type="CARGO", wheel_size_inches=26)
    receipt = validate_success(
        api_client.get_donor_receipt(d["id"], DIRECTOR, params={"year": 2026})
    )
    assert receipt["bike_count"] == 1
    assert receipt["flat_total_cents"] == 9000
    # round(12000 * 0.8 * 0.6) == 5760
    assert receipt["fmv_total_cents"] == 5760


def test_error_envelope_shape():
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api_client.get_bike(
        "00000000-0000-4000-8000-000000000000", COORD
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
