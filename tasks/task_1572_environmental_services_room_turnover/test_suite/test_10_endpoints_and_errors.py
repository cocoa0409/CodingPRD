"""Endpoint listing/pagination claims and remaining error-catalog claims."""
from test_helpers import (
    assert_instant_equal,
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_bed_payload,
    create_clean_request_payload,
    create_placement_demand_payload,
    create_supply_item_payload,
    create_unit_payload,
    get_success_data,
    make_auditor_headers,
    make_technician_headers,
    set_clock,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_bed,
    create_request,
    create_standard,
    create_staff,
    create_technician,
    create_unit,
    seed_supplies,
    start_request,
    submit_audit,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_list_endpoints_filter_paginate_and_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return. If not provided, it defaults to 10, with a minimum of 1 and
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."
    PRD §3.1: "The bed registry can be listed with optional filters on
    `unit_id`, `bed_status`, and `bed_kind`."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_endpoints_filter_paginate_and_envelope
    """
    set_clock(CLOCK_T0800)
    u1 = create_unit("U1")
    u2 = create_unit("U2", "Unit Two")
    b1 = create_bed(u1["id"], "B1", "STANDARD")
    create_bed(u1["id"], "B2", "ISOLATION")
    create_bed(u1["id"], "B3", "ICU")
    create_bed(u2["id"], "B4", "STANDARD")

    # Filter composition: unit_id + bed_kind -> exactly one row.
    filtered, fmeta = validate_paginated(
        api.list_beds(ANY, params={"unit_id": u1["id"], "bed_kind": "STANDARD"})
    )
    assert len(filtered) == 1
    assert filtered[0]["id"] == b1["id"]
    assert fmeta["total_count"] == 1
    assert fmeta["has_more"] is False

    # Pagination over three beds of U1.
    page1, p1meta = validate_paginated(
        api.list_beds(ANY, params={"unit_id": u1["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert p1meta["total_count"] == 3
    assert p1meta["has_more"] is True
    assert p1meta["limit"] == 2
    assert p1meta["offset"] == 0

    page2, p2meta = validate_paginated(
        api.list_beds(ANY, params={"unit_id": u1["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert p2meta["total_count"] == 3
    assert p2meta["has_more"] is False

    # Envelope checks on the raw response.
    raw = api.list_beds(ANY, params={"unit_id": u1["id"], "limit": 2, "offset": 0})
    body = raw.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"]
    assert "api_request_timestamp" in body["meta"]

    # Default pagination applies limit 10 / offset 0.
    default_resp = api.list_beds(ANY, params={"unit_id": u1["id"]}).json()
    assert default_resp["meta"]["limit"] == 10
    assert default_resp["meta"]["offset"] == 0


def test_productivity_endpoint_fresh_staff_defaults(api):
    """PRD §3.4: "a productivity breakdown endpoint exposes
    `productivity_score`, `verified_credit_total`, `qa_fail_count`,
    `shift_seconds_today`, `stat_eligible`, and `completed_clean_count` to any
    reader."
    PRD §3.6: "`stat_eligible` holds when the technician has no verified cleans
    yet (`completed_clean_count` is zero) or when `productivity_score` has
    reached at least 80.00."

    Design: Corner/endpoints/productivity_endpoint_fresh_staff_defaults
    """
    set_clock(CLOCK_T0800)
    tech = create_technician("T1")
    prod = get_success_data(api.get_staff_productivity(tech["id"], ANY))
    assert prod["productivity_score"] == 0
    assert prod["verified_credit_total"] == 0
    assert prod["qa_fail_count"] == 0
    assert prod["shift_seconds_today"] == 0
    assert prod["completed_clean_count"] == 0
    assert prod["stat_eligible"] is True


def test_insufficient_supply_atomic_and_names_item(api):
    """PRD §3.5: "Availability is checked per line: the item's
    `on_hand_quantity` minus its `reserved_quantity` must be at least the line
    quantity. Every line must pass; the first failing line rejects the start
    with `ERR_INSUFFICIENT_SUPPLY`, naming the item."

    Design: Corner/errors/insufficient_supply_atomic_and_names_item
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    create_standard("ISOLATION")
    create_standard("TERMINAL")
    sd = get_success_data(
        api.create_supply_item(
            create_supply_item_payload(initial_on_hand=100, reorder_threshold=10), ADMIN
        )
    )
    sp = get_success_data(
        api.create_supply_item(
            create_supply_item_payload(
                item_code="PPE_PACK",
                display_name="PPE packs",
                initial_on_hand=50,
                reorder_threshold=8,
            ),
            ADMIN,
        )
    )
    sc = get_success_data(
        api.create_supply_item(
            create_supply_item_payload(
                item_code="CLOTH",
                display_name="Cloths",
                initial_on_hand=200,
                reorder_threshold=20,
            ),
            ADMIN,
        )
    )
    ss = get_success_data(
        api.create_supply_item(
            create_supply_item_payload(
                item_code="SEALANT",
                display_name="Sealant",
                initial_on_hand=0,
                reorder_threshold=2,
            ),
            ADMIN,
        )
    )
    tech = create_technician("T1", certifications=["TERMINAL_CERT"])
    get_success_data(api.clock_in_staff(tech["id"], make_technician_headers(tech["id"])))
    bed = create_bed(unit["id"], "B1", "STANDARD")
    req = create_request(bed["id"], "TERMINAL")
    assign_request(req["id"], tech["id"])

    r = api.start_clean_request(req["id"], make_technician_headers(tech["id"]))
    err = validate_error(r, ApiErrorId.ERR_INSUFFICIENT_SUPPLY)
    assert "SEALANT" in err["message"]

    for item in (sd, sp, sc, ss):
        refreshed = get_success_data(api.get_supply_item(item["id"], ANY))
        assert refreshed["reserved_quantity"] == 0, (
            f"{refreshed['item_code']} reserved must stay 0 after an atomic rejection"
        )

    req_after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert req_after["status"] == "ASSIGNED"
    assert req_after["supply_reserved"] is False
    bed_after = get_success_data(api.get_bed(bed["id"], ANY))
    assert bed_after["bed_status"] == "VACANT_DIRTY"


def test_duplicate_clean_standard_rejected(api):
    """PRD §3.1: "There is exactly one standard row per `clean_type` —
    `ROUTINE`, `ISOLATION`, or `TERMINAL` — and creating a second row for a
    type that already has one is rejected with `ERR_DUPLICATE_STANDARD`."

    Design: Corner/errors/duplicate_clean_standard_rejected
    """
    set_clock(CLOCK_T0800)
    first = get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    r = api.create_clean_standard(
        {
            "clean_type": "ROUTINE",
            "base_minutes": 99,
            "outbreak_multiplier_bps": 10000,
            "atp_rlu_threshold": 500,
        },
        ADMIN,
    )
    validate_error(r, ApiErrorId.ERR_DUPLICATE_STANDARD)

    row = get_success_data(api.get_clean_standard("ROUTINE", ANY))
    assert row["base_minutes"] == 45
    assert row["atp_rlu_threshold"] == 250
    assert row["version"] == first["version"]


def test_clock_regression_rejected_and_equality_allowed(api):
    """PRD §2.4: "The clock is monotonic: the supplied instant must be at or
    after the current logical time, and an attempt to move it backward is
    rejected with `ERR_CLOCK_REGRESSION`."

    Design: Corner/errors/clock_regression_rejected_and_equality_allowed
    """
    set_clock(CLOCK_T0800)
    r = api.set_clock({"to_iso8601": "2026-08-01T07:59:00Z"}, ADMIN)
    validate_error(r, ApiErrorId.ERR_CLOCK_REGRESSION)

    same = get_success_data(api.set_clock({"to_iso8601": CLOCK_T0800}, ADMIN))
    assert_instant_equal(same["current_utc"], CLOCK_T0800)


def test_stat_assignment_requires_eligible_staff(api):
    """PRD §3.4: "a `STAT`-tier request may go only to a staff member whose
    `stat_eligible` is true (`ERR_STAFF_NOT_STAT_ELIGIBLE`)."
    PRD §3.6: "otherwise it is one hundred times `verified_credit_total`
    divided by the shift hours — `shift_seconds_today` divided by 3600 — minus
    a penalty of 5.00 points per `qa_fail_count`."

    Design: Corner/errors/stat_assignment_requires_eligible_staff
    """
    ctx = setup_basic_scenario()
    tech = ctx["tech"]
    bed2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")

    # One verified ROUTINE clean (credit 1.00), then close a 2h shift -> 50.00.
    r1 = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(r1["id"], tech["id"])
    start_request(r1["id"], tech["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(r1["id"], tech["id"])
    submit_audit(r1["id"], ctx["auditor"]["id"], rlu_reading=100)
    set_clock("2026-08-01T10:00:00Z")
    get_success_data(api.clock_out_staff(tech["id"], make_technician_headers(tech["id"])))
    get_success_data(api.clock_in_staff(tech["id"], make_technician_headers(tech["id"])))

    staff = get_success_data(api.get_staff(tech["id"], ANY))
    assert staff["productivity_score"] == 50.0
    assert staff["stat_eligible"] is False

    # STAT demand for STANDARD beds -> fresh request becomes STAT-tier.
    get_success_data(
        api.create_placement_demand(
            create_placement_demand_payload(
                unit_id=ctx["unit"]["id"], urgency_tier="STAT"
            ),
            COORDINATOR,
        )
    )
    r2 = create_request(bed2["id"], "ROUTINE")
    assert r2["priority_tier"] == "STAT"

    r = api.assign_clean_request(r2["id"], {"staff_id": tech["id"]}, DISPATCHER)
    validate_error(r, ApiErrorId.ERR_STAFF_NOT_STAT_ELIGIBLE)

    after = get_success_data(api.get_clean_request(r2["id"], ANY))
    assert after["status"] == "QUEUED"
    assert after["assigned_staff_id"] is None


def test_reclean_requires_different_technician(api):
    """PRD §3.4: "For a reclean assignment there is one more gate: the
    second-set-of-hands rule requires the new `staff_id` to differ from the
    request's `last_completed_by_staff_id`, so the technician whose work failed
    QA never picks up their own reclean (`ERR_RECLEAN_SAME_TECHNICIAN`)."

    Design: Corner/errors/reclean_requires_different_technician
    """
    ctx = setup_basic_scenario()
    t2 = create_technician("T2")
    req = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(req["id"], ctx["tech"]["id"])
    start_request(req["id"], ctx["tech"]["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(req["id"], ctx["tech"]["id"])
    submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=300)

    r = api.assign_clean_request(req["id"], {"staff_id": ctx["tech"]["id"]}, DISPATCHER)
    validate_error(r, ApiErrorId.ERR_RECLEAN_SAME_TECHNICIAN)

    ok = validate_success(
        api.assign_clean_request(req["id"], {"staff_id": t2["id"]}, DISPATCHER)
    )
    assert ok["assigned_staff_id"] == t2["id"]
    assert ok["status"] == "ASSIGNED"
    assert ok["reclean_count"] == 1
