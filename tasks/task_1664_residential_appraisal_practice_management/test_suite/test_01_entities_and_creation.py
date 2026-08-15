"""Entity creation claims: declared defaults, initial states, and computed
fields written at creation time (PRD 3.1-3.8)."""
from test_helpers import (
    ApiErrorId,
    add_standard_locked_comps,
    assert_client,
    assert_complaint,
    assert_appraiser,
    assert_comparable,
    assert_order,
    assert_panel_membership,
    create_appraiser,
    create_client,
    create_fee_schedule,
    create_membership,
    create_order,
    create_revision_request,
    create_trainee,
    first_workfile_of_type,
    get_order,
    get_scorecard,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_workfiles,
    scope_order,
    accept_order,
    set_clock,
    setup_accepted_order,
    setup_assigned_order,
    setup_delivered_order,
    setup_order_in_analysis,
    setup_order_with_report,
    start_analysis,
    validate_success,
    create_appraiser_payload,
    create_client_payload,
    create_fee_schedule_payload,
    create_order_payload,
    create_panel_membership_payload,
    create_workfile_record_payload,
    create_complaint_payload,
    create_comparable_payload,
    make_appraiser_headers,
    make_clientuser_headers,
)
from test_helpers import ADMIN, COMPLIANCE


def test_client_creation_defaults_and_round_trip(api):
    """PRD 3.1: "A new client starts in `ACTIVE` status."
    PRD 2.5: "`id` (string): a unique, server-minted identifier formatted as
    a UUID, with no type prefix."

    Design: Corner/entities/client_creation_retrieval_defaults
    """
    response = api.create_client(
        create_client_payload(
            name="First Client",
            client_type="DIRECT_LENDER",
            contact_email="ops@c1.example",
            default_turn_time_days=5,
        ),
        ADMIN,
    )
    client = validate_success(response, 201)
    assert_client(client)
    assert client["status"] == "ACTIVE"
    assert isinstance(client["version"], int) and client["version"] >= 1
    assert is_iso8601_timestamp(client["created_at"])

    fetched = validate_success(api.get_client(client["id"], ADMIN), 200)
    assert fetched["name"] == "First Client"
    assert fetched["status"] == "ACTIVE"
    assert fetched["id"] == client["id"]


def test_appraiser_creation_computed_defaults(api):
    """PRD 3.2: "A new appraiser starts `ACTIVE`, with `sanction_override`
    false and all performance counters at zero."
    PRD 3.2: "The `on_time_rate` is null while the appraiser has no
    completions, and otherwise is the count of on-time deliveries divided by
    `completed_count`, rounded half-up to four decimal places."

    Design: Corner/entities/appraiser_creation_retrieval_computed_defaults
    """
    set_clock("2026-08-01T00:00:00Z")
    response = api.create_appraiser(
        create_appraiser_payload(
            full_name="New Appraiser",
            license_level="CERTIFIED_RESIDENTIAL",
            license_number="CR-9",
            license_expiry="2027-06-01",
        ),
        ADMIN,
    )
    appraiser = validate_success(response, 201)
    assert_appraiser(appraiser)
    assert appraiser["status"] == "ACTIVE"
    assert appraiser["sanction_override"] is False

    scorecard = validate_success(api.get_scorecard(appraiser["id"], ADMIN), 200)
    assert scorecard["completed_count"] == 0
    assert scorecard["on_time_count"] == 0
    assert scorecard.get("on_time_rate") is None
    assert scorecard["standing"] == "GOOD_STANDING"
    assert scorecard["confirmed_minutes"] == 0


def test_trainee_appraiser_requires_certified_supervisor(api):
    """PRD 3.2: "the field is required exactly when `license_level` is
    `TRAINEE` and is forbidden for any other level, and the referenced
    supervisor must itself hold `CERTIFIED_RESIDENTIAL` — otherwise creation
    is rejected with `ERR_SUPERVISOR_NOT_CERTIFIED`."
    PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/trainee_appraiser_requires_certified_supervisor
    """
    set_clock("2026-08-01T00:00:00Z")
    licensed = create_appraiser(
        full_name="Larry Licensed", license_level="LICENSED", license_number="LA-1"
    )
    supervisor = create_appraiser(
        full_name="Sara Supervisor",
        license_level="CERTIFIED_RESIDENTIAL",
        license_number="CR-1",
    )

    missing = api.create_appraiser(
        create_appraiser_payload(
            full_name="Tina Trainee", license_level="TRAINEE", license_number="TR-1"
        ),
        ADMIN,
    )
    from test_helpers import validate_error

    validate_error(missing, ApiErrorId.ERR_VALIDATION)

    wrong_level = api.create_appraiser(
        create_appraiser_payload(
            full_name="Tina Trainee",
            license_level="TRAINEE",
            license_number="TR-1",
            supervisor_id=licensed["id"],
        ),
        ADMIN,
    )
    validate_error(wrong_level, ApiErrorId.ERR_SUPERVISOR_NOT_CERTIFIED)

    ok = api.create_appraiser(
        create_appraiser_payload(
            full_name="Tina Trainee",
            license_level="TRAINEE",
            license_number="TR-1",
            supervisor_id=supervisor["id"],
        ),
        ADMIN,
    )
    trainee = validate_success(ok, 201)
    assert trainee["supervisor_id"] == supervisor["id"]


def test_panel_membership_creation_and_round_trip(api):
    """PRD 3.1: "A `FirmAdmin` adds an appraiser to a client's panel by
    creating a membership carrying the `client_id` and the `appraiser_id`;
    the membership starts `ACTIVE`."

    Design: Corner/entities/panel_membership_creation_retrieval
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    appraiser = create_appraiser()

    response = api.create_panel_membership(
        create_panel_membership_payload(client["id"], appraiser["id"]), ADMIN
    )
    membership = validate_success(response, 201)
    assert_panel_membership(membership)
    assert membership["status"] == "ACTIVE"

    fetched = validate_success(api.get_panel_membership(membership["id"], ADMIN), 200)
    assert fetched["client_id"] == client["id"]
    assert fetched["appraiser_id"] == appraiser["id"]


def test_fee_schedule_creation_open_ended_default(api):
    """PRD 3.1: "an optional `effective_to` marking the exclusive end of the
    window — null means open-ended."

    Design: Corner/entities/fee_schedule_creation_open_ended_default
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    payload = create_fee_schedule_payload(
        client["id"],
        client["version"],
        complexity_tier="COMPLEX",
        base_fee_cents=60000,
        rush_multiplier_bps=1500,
        revision_fee_cents=15000,
        effective_from="2026-07-01T00:00:00Z",
    )
    schedule = validate_success(api.create_fee_schedule(payload, ADMIN), 201)
    assert schedule.get("effective_to") is None, "omitted effective_to is open-ended"

    fetched = validate_success(api.get_fee_schedule(schedule["id"], ADMIN), 200)
    assert fetched["base_fee_cents"] == 60000


def test_order_creation_initial_state_and_round_trip(api):
    """PRD 3.3: "A new order begins in `RECEIVED` with `requires_inspection`
    defaulting to true, no assignee, and its monetary counters —
    `surcharge_total_cents`, `waived_total_cents`, and
    `revision_fees_collected_cents` — at zero."

    Design: Corner/entities/order_creation_retrieval_initial_state
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    response = api.create_order(
        create_order_payload(
            client["id"],
            property_address="5 New St",
            property_type="CONDO",
            estimated_value_cents=30000000,
            loan_type="VA",
            requested_turn_days=10,
        ),
        make_clientuser_headers(client["id"]),
    )
    order = validate_success(response, 201)
    assert_order(order)
    assert order["status"] == "RECEIVED"
    assert order["requires_inspection"] is True
    assert order.get("assigned_appraiser_id") is None
    assert order["surcharge_total_cents"] == 0
    assert order["waived_total_cents"] == 0
    assert order["revision_fees_collected_cents"] == 0
    assert order["open_complaint_count"] == 0

    fetched = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert fetched["status"] == "RECEIVED"
    assert fetched["property_type"] == "CONDO"


def test_appointment_creation_initial_state(api):
    """PRD 3.4: "A new appointment starts `PROPOSED`."
    PRD 3.4: "The first confirmation for an order automatically advances the
    order from `ASSIGNED` to `INSPECTION_SCHEDULED`."

    Design: Corner/entities/appointment_creation_initial_state
    """
    ctx = setup_assigned_order(desktop=False)
    response = api.create_appointment(
        {
            "order_id": ctx["order"]["id"],
            "appraiser_id": ctx["appraiser"]["id"],
            "window_start": "2026-08-02T09:00:00Z",
            "window_end": "2026-08-02T10:00:00Z",
        },
        ctx["appraiser_headers"],
    )
    appointment = validate_success(response, 201)
    assert appointment["status"] == "PROPOSED"

    order = validate_success(api.get_order(ctx["order"]["id"], ADMIN), 200)
    assert order["status"] == "ASSIGNED", "order advances only on confirm"


def test_comparable_creation_computed_and_default_fields(api):
    """PRD 3.5: "with `other_adjustment_cents` defaulting to 0 when omitted.
    A comparable starts in `DRAFT`."
    PRD 3.5: "Each of the four signed lines is rounded individually first:
    divided by 10000, rounded half-up to a whole number, and multiplied back
    by 10000, so every line lands on a whole hundred dollars before any
    summation takes place."
    PRD 3.5: "The comparable's `adjusted_price_cents` is then its
    `sale_price_cents` plus the sum of the four rounded lines."

    Design: Corner/entities/comparable_creation_computed_and_default_fields
    """
    ctx = setup_order_in_analysis()
    response = api.create_comparable(
        create_comparable_payload(
            ctx["order"]["id"],
            address="9 Cmp Rd",
            sale_price_cents=45250000,
            sale_date="2026-06-01",
            distance_miles=0.30,
            site_adjustment_cents=0,
            gla_adjustment_cents=0,
            condition_adjustment_cents=6000,
        ),
        ctx["appraiser_headers"],
    )
    comp = validate_success(response, 201)
    assert_comparable(comp)
    assert comp["other_adjustment_cents"] == 0
    # single +6000 line rounds to +10000 before summation
    assert comp["adjusted_price_cents"] == 45260000
    assert comp["status"] == "DRAFT"


def test_report_creation_system_fields_and_one_per_order(api):
    """PRD 3.6: "The new report's `signing_appraiser_id` is set to the order's
    assigned appraiser, `revision_round` and `qc_fail_count` start at 0, the
    status begins at `DRAFT`, and a `COMP_DATA` workfile record is filed for
    the order."
    PRD 3.6: "The order must be `IN_ANALYSIS`; because creation moves the
    order to `DRAFTING`, a second creation attempt finds the order no longer
    in that state and fails with `ERR_INVALID_STATE` — which is how the
    one-report-per-order rule is enforced."
    PRD 3.6: "The raw conclusion is the weighted mean — the sum of each weight
    times its comparable's `adjusted_price_cents`, divided by the sum of the
    weights — carried exactly, without intermediate rounding."

    Design: Corner/entities/report_creation_system_fields
    """
    from test_helpers import validate_error

    ctx = setup_order_in_analysis()
    add_standard_locked_comps(ctx)
    response = api.create_report(
        {
            "order_id": ctx["order"]["id"],
            "report_type": "FORM_1073",
            "condition_rating": "C2",
        },
        ctx["appraiser_headers"],
    )
    report = validate_success(response, 201)
    assert report["signing_appraiser_id"] == ctx["appraiser"]["id"]
    assert report["revision_round"] == 0
    assert report["qc_fail_count"] == 0
    assert report["status"] == "DRAFT"
    # weights 3/2/1 over 44500000/45700000/45000000 -> 44983333.33 -> 45000000
    assert report["value_conclusion_cents"] == 45000000

    second = api.create_report(
        {
            "order_id": ctx["order"]["id"],
            "report_type": "FORM_1004",
            "condition_rating": "C3",
        },
        ctx["appraiser_headers"],
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)


def test_revision_request_creation_open_and_order_version_bump(api):
    """PRD 3.7: "The new request starts `OPEN`, and if another request was
    already `OPEN` on the same order, the earlier one is moved to `SUPERSEDED`
    as part of the same write — which is exactly why the order's `version`
    advances at creation and why the concurrency guard exists."

    Design: Corner/entities/revision_request_creation_open_state_and_version_bump
    """
    ctx = setup_delivered_order()
    before = get_order(ctx["order"]["id"])["version"]

    response = api.create_revision_request(
        ctx["order"]["id"],
        {
            "kind": "CORRECTION",
            "detail": "Typo in address",
            "expected_order_version": before,
        },
        ctx["client_headers"],
    )
    rr = validate_success(response, 201)
    assert rr["status"] == "OPEN"
    assert rr["order_id"] == ctx["order"]["id"]

    after = get_order(ctx["order"]["id"])["version"]
    assert after == before + 1, "creating a revision request advances the order version by exactly one"


def test_workfile_creation_active_with_null_retention_predelivery(api):
    """PRD 3.8: "a `snapshot_type` of `ORDER_FORM`, `INSPECTION_NOTES`,
    `COMP_DATA`, `REPORT_PDF`, `CERTIFICATION`, or `REVISION_CORRESPONDENCE`,
    a system-stamped `recorded_at`, and a status that begins at `ACTIVE`."
    PRD 3.8: "Retention is pinned at first delivery, and not before: a
    record's `retention_until` stays null — and the record stays unpurgeable
    — until the order's first delivery."
    PRD 3.3: "Acceptance also stamps `accepted_at` with the logical clock,
    computes `due_at` as exactly `requested_turn_days` calendar days after
    `accepted_at`, and opens the order's workfile by filing an `ORDER_FORM`
    record."

    Design: Corner/entities/workfile_record_creation_and_null_retention_predelivery
    """
    ctx = setup_accepted_order()
    response = api.create_workfile_record(
        create_workfile_record_payload(ctx["order"]["id"], "COMP_DATA"), ADMIN
    )
    record = validate_success(response, 201)
    assert record["status"] == "ACTIVE"
    assert record.get("retention_until") is None, "no pin before first delivery"

    order_form = first_workfile_of_type(ctx["order"]["id"], "ORDER_FORM")
    assert order_form["snapshot_type"] == "ORDER_FORM"
    assert is_valid_uuid(order_form["id"])


def test_complaint_creation_computed_deadline(api):
    """PRD 3.8: "Intake stamps `received_at` with the logical clock, computes
    `response_due_at` as exactly 21 days later, increments the order's
    `open_complaint_count` by one, and sweeps every `ACTIVE` workfile record
    of the order into `LEGAL_HOLD`."

    Design: Corner/entities/complaint_creation_computed_deadline
    """
    ctx = setup_delivered_order()
    set_clock("2026-08-10T00:00:00Z")
    response = api.create_complaint(
        create_complaint_payload(
            ctx["order"]["id"], ctx["appraiser"]["id"], description="Board letter"
        ),
        COMPLIANCE,
    )
    complaint = validate_success(response, 201)
    assert_complaint(complaint)
    assert complaint["status"] == "RECEIVED"
    assert complaint["received_at"] == "2026-08-10T00:00:00Z"
    assert complaint["response_due_at"] == "2026-08-31T00:00:00Z"

    fetched = validate_success(api.get_complaint(complaint["id"], COMPLIANCE), 200)
    assert fetched["status"] == "RECEIVED"
