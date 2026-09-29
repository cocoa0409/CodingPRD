"""State-machine behaviour of the Winery DTC Shipping Compliance API.

Declared initial states, legal transitions and their side effects, refused
transitions, terminal lock-down and the transitions the system performs on its
own initiative.  Every expectation below is quoted from PRD.md and nothing else.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (client under test)
from test_helpers.assertions import (
    assert_cents,
    assert_instant_equals,
    assert_ledger_entry,
    assert_liters,
    assert_order_dimensions,
    assert_rejection,
    assert_versioned_identity,
)
from test_helpers.constants import CLOCK_DEFAULT_CANONICAL
from test_helpers.fixtures import (
    append_manual_adjustment,
    build_landscape,
    create_active_permit,
    create_permit,
    create_state_rule,
    create_winery,
    set_clock,
)
from test_helpers.test_users import OFFICER_A, make_carrier_headers


def _rows(response):
    """The data array of a list response, together with its meta window."""
    return validate_paginated(response)


def _ledger_for_order(landscape, order_id):
    """Every ledger row attached to one order.

    The whole collection is listed and narrowed here rather than through a query
    parameter, because the only list parameters this contract declares are
    ``limit`` and ``offset`` (PRD 2.3).  The database is empty at the start of
    each test, so the listing is complete.
    """
    return [row for row in landscape.ledger_rows() if row.get("order_id") == order_id]


# ---------------------------------------------------------------------------
# CarrierEnrollment: PENDING -> APPROVED
# ---------------------------------------------------------------------------
def test_enrollment_decision_moves_pending_to_approved_and_stamps_the_decider(api):
    """Approval flips the status and executes both of its declared stamps.

    "A new enrollment opens in `status` `PENDING` with `approved_at` and
    `decided_by_user_id` both null." (PRD 3.3)

    "Every decision records `decided_by_user_id` from the deciding agent's
    `X-User-ID`, and every decision that lands on `APPROVED` — first approval or
    reinstatement alike — stamps `approved_at` from the logical clock." (PRD 3.3)

    "A decision that merely repeats the enrollment's current standing, such as
    approving an already `APPROVED` enrollment, is refused with
    `ERR_ENROLLMENT_ALREADY_DECIDED` (HTTP 409)." (PRD 3.3)

    Design: Corner/state_machines/enrollment_decision_moves_pending_to_approved_and_stamps_the_decider
    """
    landscape = build_landscape(api, approve_enrollment=False)

    before = validate_success(
        api.get_carrier_enrollment(landscape.enrollment_id, OFFICER_A),
        expected_status=200,
    )
    assert before["status"] == "PENDING"
    assert before["approved_at"] is None
    assert before["decided_by_user_id"] is None

    agent = make_carrier_headers("agent_1")
    data = validate_success(
        api.decide_carrier_enrollment(
            landscape.enrollment_id,
            f.enrollment_decision_payload("APPROVED",
                                          "Wine shipper agreement on file"),
            agent,
        ),
        expected_status=200,
    )

    assert data["status"] == "APPROVED"
    assert_instant_equals(data["approved_at"], CLOCK_DEFAULT_CANONICAL)
    assert data["decided_by_user_id"] == "agent_1"
    assert data["winery_id"] == landscape.winery_id
    assert data["carrier_program_id"] == landscape.program_id
    assert_versioned_identity(data, expected_version=2)

    validate_error(
        api.decide_carrier_enrollment(
            landscape.enrollment_id, f.enrollment_decision_payload("APPROVED"), agent
        ),
        "ERR_ENROLLMENT_ALREADY_DECIDED", expected_status=409,
    )


# ---------------------------------------------------------------------------
# StatePermit: PENDING -> ACTIVE
# ---------------------------------------------------------------------------
def test_permit_activation_before_the_effective_date_is_refused(api):
    """Activation waits for the effective date and the comparison is inclusive.

    "A `ComplianceOfficer` activates it — a `PENDING` → `ACTIVE` move — and that
    is only permitted once the permit's `effective_date` has arrived, meaning
    `effective_date` falls on or before the logical clock date. Activation from
    any state other than `PENDING` is refused with
    `ERR_INVALID_STATE_TRANSITION`." (PRD 3.2)

    "A filed permit opens in `PENDING`, and a `PENDING` permit authorizes
    nothing." (PRD 3.2)

    Design: Corner/state_machines/permit_activation_before_the_effective_date_is_refused
    """
    set_clock(api, "2025-12-01T00:00:00Z")
    winery = create_winery(api)
    create_state_rule(api)
    permit = create_permit(
        api, winery["id"], effective_date="2026-01-01", expiration_date="2026-12-31"
    )
    assert permit["status"] == "PENDING"

    validate_error(
        api.activate_state_permit(permit["id"], {}, OFFICER_A),
        "ERR_INVALID_STATE_TRANSITION", expected_status=409,
    )
    still_pending = validate_success(
        api.get_state_permit(permit["id"], OFFICER_A), expected_status=200
    )
    assert still_pending["status"] == "PENDING"

    set_clock(api, "2026-01-01T00:00:00Z")
    data = validate_success(
        api.activate_state_permit(permit["id"], {}, OFFICER_A), expected_status=200
    )

    assert data["status"] == "ACTIVE"
    assert data["effective_date"] == "2026-01-01"
    assert data["expiration_date"] == "2026-12-31"
    assert data["renewal_cycle_count"] == 0
    assert data["revocation_reason"] is None
    assert_versioned_identity(data, expected_version=2)


# ---------------------------------------------------------------------------
# StatePermit: ACTIVE -> RENEWAL_FILED -> ACTIVE
# ---------------------------------------------------------------------------
def test_renewal_cycle_files_then_approves_and_extends_the_same_row(api, clock):
    """Filing records its two fields; approval extends the row and clears them.

    "Filing a renewal — available to both a `ComplianceOfficer` and the
    `WineryOperator` that holds the permit — records a `renewal_reference`
    supplied in the request and stamps `renewal_filed_at` from the logical
    clock." (PRD 3.2)

    "On success the permit's `expiration_date` is replaced by the supplied value,
    `renewal_cycle_count` is increased by 1, and both `renewal_reference` and
    `renewal_filed_at` are cleared back to null — leaving the row ready to repeat
    the same `ACTIVE` → `RENEWAL_FILED` → `ACTIVE` cycle at the next expiry."
    (PRD 3.2)

    "Renewal is a cycle that returns the same permit row to `ACTIVE` rather than
    creating a new row." (PRD 3.2)

    Design: Corner/state_machines/renewal_cycle_files_then_approves_and_extends_the_same_row
    """
    winery = create_winery(api)
    create_state_rule(api)
    permit = create_active_permit(
        api, winery["id"], effective_date="2026-01-01", expiration_date="2026-09-14"
    )

    filed = validate_success(
        api.file_permit_renewal(
            permit["id"], f.file_renewal_payload("TX-RN-2027"), OFFICER_A
        ),
        expected_status=200,
    )
    assert filed["status"] == "RENEWAL_FILED"
    assert filed["renewal_reference"] == "TX-RN-2027"
    assert_instant_equals(filed["renewal_filed_at"], CLOCK_DEFAULT_CANONICAL)

    approved = validate_success(
        api.approve_permit_renewal(
            permit["id"], f.approve_renewal_payload("2027-09-14"), OFFICER_A
        ),
        expected_status=200,
    )
    assert approved["status"] == "ACTIVE"
    assert approved["expiration_date"] == "2027-09-14"
    assert approved["renewal_cycle_count"] == 1
    assert approved["renewal_reference"] is None
    assert approved["renewal_filed_at"] is None
    assert approved["id"] == permit["id"]
    assert_versioned_identity(approved, expected_version=4)

    permits, meta = _rows(api.list_state_permits(OFFICER_A, {"limit": 100}))
    assert len(permits) == 1
    assert meta["total_count"] == 1
    assert permits[0]["id"] == permit["id"]

    validate_error(
        api.approve_permit_renewal(
            permit["id"], f.approve_renewal_payload("2028-09-14"), OFFICER_A
        ),
        "ERR_INVALID_STATE_TRANSITION", expected_status=409,
    )


# ---------------------------------------------------------------------------
# Shipment: scans that are not declared from the current status
# ---------------------------------------------------------------------------
def test_scans_not_declared_from_the_current_shipment_status_are_refused(
    in_transit_order,
):
    """A second pickup and a reroute outside EXCEPTION are both 409, and inert.

    "A scan type that is not declared from the shipment's current status — a
    pickup on a shipment already `IN_TRANSIT`, a reroute on a shipment that is
    not in `EXCEPTION`, a second reroute on a shipment that has already been
    rerouted once, or any scan at all on a shipment that has reached `DELIVERED`
    or `RETURNED` — is refused with `ERR_SHIPMENT_NOT_ACTIVE` (HTTP 409)."
    (PRD 3.7)

    "A **`REROUTE_ACCEPTED`** scan moves the shipment `EXCEPTION` → `IN_TRANSIT`,
    closing the `IN_TRANSIT` → `EXCEPTION` → `IN_TRANSIT` cycle, and carries a
    `reroute_zip` and a `reroute_state_code`." (PRD 3.7)

    Design: Corner/state_machines/scans_not_declared_from_the_current_shipment_status_are_refused
    """
    landscape, order, shipment = in_transit_order
    api = landscape.api
    agent = make_carrier_headers("agent_1")

    validate_error(
        api.scan_shipment(shipment["id"], f.pickup_scan(), agent),
        "ERR_SHIPMENT_NOT_ACTIVE", expected_status=409,
    )
    validate_error(
        api.scan_shipment(
            shipment["id"], f.reroute_scan("78702", "TX"), agent
        ),
        "ERR_SHIPMENT_NOT_ACTIVE", expected_status=409,
    )

    stored = landscape.read_shipment(shipment["id"])
    assert stored["status"] == "IN_TRANSIT"
    assert stored["reroute_count"] == 0
    assert stored["reroute_zip"] is None
    assert stored["exception_code"] is None

    assert_order_dimensions(
        landscape.read_order(order["id"]), fulfillment_status="IN_TRANSIT"
    )

    assert len(_ledger_for_order(landscape, order["id"])) == 1


# ---------------------------------------------------------------------------
# Declared initial states
# ---------------------------------------------------------------------------
def test_newly_created_rows_start_in_their_declared_initial_state(api):
    """Four machines report their opening state straight off the create call.

    "A new subscription opens in `status` `ACTIVE`, with `missed_run_count` and
    `consumed_shipments` at 0, `remaining_allotment` equal to
    `annual_allotment`, and `hold_start_date`, `hold_release_date`, `hold_reason`
    and `last_hold_release_date` all null." (PRD 3.8)

    "A filed permit opens in `PENDING`, and a `PENDING` permit authorizes
    nothing." (PRD 3.2)

    "A new enrollment opens in `status` `PENDING` with `approved_at` and
    `decided_by_user_id` both null." (PRD 3.3)

    "The order itself opens with `compliance_status` `DRAFT` and
    `fulfillment_status` `UNFULFILLED`" (PRD 3.5)

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    landscape = build_landscape(
        api, activate_permit_row=False, approve_enrollment=False
    )

    subscription = validate_success(
        api.create_club_subscription(
            f.club_subscription_payload(
                landscape.consumer_id, landscape.winery_id,
                next_run_date="2026-08-15",
            ),
            landscape.operator,
        ),
        expected_status=201,
    )

    assert subscription["status"] == "ACTIVE"
    assert subscription["hold_start_date"] is None
    assert subscription["hold_release_date"] is None
    assert subscription["hold_reason"] is None
    assert subscription["last_hold_release_date"] is None
    assert subscription["missed_run_count"] == 0
    assert subscription["consumed_shipments"] == 0
    assert subscription["remaining_allotment"] == 12

    assert landscape.read_permit()["status"] == "PENDING"

    enrollment = validate_success(
        api.get_carrier_enrollment(landscape.enrollment_id, OFFICER_A),
        expected_status=200,
    )
    assert enrollment["status"] == "PENDING"
    assert enrollment["approved_at"] is None

    order = validate_success(
        api.create_order(
            f.order_payload(
                landscape.winery_id, landscape.consumer_id,
                landscape.consumer_version(),
            ),
            landscape.operator,
        ),
        expected_status=201,
    )
    assert_order_dimensions(order, compliance_status="DRAFT",
                            fulfillment_status="UNFULFILLED")


# ---------------------------------------------------------------------------
# Shipment: DELIVERED is terminal
# ---------------------------------------------------------------------------
def test_delivered_shipment_is_locked_against_every_further_scan(in_transit_order):
    """Delivery needs its signature, and nothing may follow the delivery.

    "When the shipment's `adult_signature_required` is true the scan must carry a
    non-empty `signed_by` string **and** a `signer_age_verified` of true; a
    missing signer name or an unverified signer is refused with
    `ERR_INVALID_REQUEST`." (PRD 3.7)

    "On success the shipment's `delivered_at` is stamped from the logical clock,
    `signed_by` and `signer_age_verified` are recorded, and the order's
    `fulfillment_status` becomes `DELIVERED`" (PRD 3.7)

    "A scan type that is not declared from the shipment's current status — a
    pickup on a shipment already `IN_TRANSIT`, a reroute on a shipment that is
    not in `EXCEPTION`, a second reroute on a shipment that has already been
    rerouted once, or any scan at all on a shipment that has reached `DELIVERED`
    or `RETURNED` — is refused with `ERR_SHIPMENT_NOT_ACTIVE` (HTTP 409)."
    (PRD 3.7)

    Design: Corner/state_machines/delivered_shipment_is_locked_against_every_further_scan
    """
    landscape, order, shipment = in_transit_order
    api = landscape.api
    agent = make_carrier_headers("agent_1")

    assert landscape.read_shipment(shipment["id"])["adult_signature_required"] is True

    validate_error(
        api.scan_shipment(shipment["id"], f.scan_payload("DELIVERED"), agent),
        "ERR_INVALID_REQUEST", expected_status=400,
    )
    assert landscape.read_shipment(shipment["id"])["status"] == "IN_TRANSIT"

    delivered = validate_success(
        api.scan_shipment(
            shipment["id"],
            f.delivered_scan(signed_by="Ada Buyer", signer_age_verified=True),
            agent,
        ),
        expected_status=200,
    )
    assert delivered["status"] == "DELIVERED"
    assert_instant_equals(delivered["delivered_at"], CLOCK_DEFAULT_CANONICAL)
    assert delivered["signed_by"] == "Ada Buyer"
    assert delivered["signer_age_verified"] is True

    stored_order = landscape.read_order(order["id"])
    assert_order_dimensions(stored_order, compliance_status="CLEARED",
                            fulfillment_status="DELIVERED")

    validate_error(
        api.scan_shipment(shipment["id"], f.return_scan(), agent),
        "ERR_SHIPMENT_NOT_ACTIVE", expected_status=409,
    )

    stored_order = landscape.read_order(order["id"])
    assert_cents(stored_order["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(landscape.read_winery()["excise_reversed_cents"], 0,
                 "excise_reversed_cents")
    assert len(_ledger_for_order(landscape, order["id"])) == 1
    assert landscape.read_consumer()["return_credit_count"] == 0


# ---------------------------------------------------------------------------
# Order: screening is single-shot, not idempotent
# ---------------------------------------------------------------------------
def test_screening_a_cleared_order_a_second_time_is_refused_and_changes_nothing(
    cleared_order,
):
    """The refused re-screen re-runs none of the clearance side effects.

    "Only two starting states admit a screen: `DRAFT`, the ordinary case, and
    `SUSPENDED_PERMIT`, the re-screen of an order that a revocation had frozen.
    An order already sitting at `CLEARED`, `REJECTED` or `OVERRIDE_PENDING`
    cannot be screened again, and the attempt is refused with
    `ERR_ORDER_ALREADY_SCREENED` (HTTP 409)." (PRD 3.6)

    "It appends a volume-ledger entry with `event_type` `SHIPMENT_ACCEPTED`,
    `liters` equal to positive `total_liters`" and "The winery's
    `excise_accrued_cents` grows by the order's `excise_tax_cents`" (PRD 3.6)

    Design: Corner/state_machines/screening_a_cleared_order_a_second_time_is_refused_and_changes_nothing
    """
    landscape, order = cleared_order
    api = landscape.api
    version_before = landscape.consumer_version()

    validate_error(
        api.screen_order(order["id"], {}, OFFICER_A),
        "ERR_ORDER_ALREADY_SCREENED", expected_status=409,
    )

    rows = _ledger_for_order(landscape, order["id"])
    assert len(rows) == 1
    assert_ledger_entry(
        rows[0], event_type="SHIPMENT_ACCEPTED", liters=4.500, state_code="TX",
        order_id=order["id"],
    )

    assert_cents(
        landscape.read_winery()["excise_accrued_cents"], 211, "excise_accrued_cents"
    )

    consumer = landscape.read_consumer()
    assert consumer["version"] == version_before
    assert_liters(consumer["rolling_liters_by_state"]["TX"], 4.500, "rolling TX liters")

    stored = landscape.read_order(order["id"])
    assert_order_dimensions(stored, compliance_status="CLEARED")
    assert_instant_equals(stored["cleared_at"], CLOCK_DEFAULT_CANONICAL)


# ---------------------------------------------------------------------------
# ComplianceException: OPEN -> APPROVED, and OVERRIDE_PENDING -> CLEARED
# ---------------------------------------------------------------------------
def test_approving_an_exception_replays_the_full_clearance_ledger_chain(api, landscape):
    """The approval door is the only way the rolling total may pass the limit.

    "A **`DRAFT` → `OVERRIDE_PENDING`** outcome likewise writes the overridable
    identifier into `rejection_error_id` and appends no ledger entry — the liters
    are not reserved while the exception is pending." (PRD 3.6)

    "An **`OPEN` → `APPROVED`** decision moves the order `OVERRIDE_PENDING` →
    `CLEARED`, sets its `override_applied` flag to true, clears its
    `rejection_error_id` to null, and stamps `cleared_at` from the logical clock.
    The full clearance chain then fires exactly as it does for a `DRAFT` →
    `CLEARED` screen: a `SHIPMENT_ACCEPTED` entry is appended for the positive
    `total_liters`, the consumer's rolling and risk fields are recomputed with
    `Consumer.version` incrementing, the winery's `excise_accrued_cents` grows by
    the order's `excise_tax_cents`, and a named club subscription has its
    `consumed_shipments` and `remaining_allotment` moved. The winery's
    `open_exception_count` falls by 1." (PRD 3.6)

    "the exception's `status` must be `OPEN`, or the call is refused with
    `ERR_EXCEPTION_ALREADY_DECIDED`" (PRD 3.6)

    "`screening_tier`, which is `STANDARD` while `risk_score_screening` is below
    50" (PRD 3.4), and the screening variant's "utilisation term reads
    `rolling_liters_settled_by_state`" (PRD 3.4), which excludes this still
    `UNFULFILLED` order.

    Design: Corner/state_machines/approving_an_exception_replays_the_full_clearance_ledger_chain
    """
    append_manual_adjustment(
        api, landscape.consumer_id, landscape.winery_id, 25.000,
        occurred_at="2026-07-01T00:00:00Z",
        reason="Pre-platform TX volume for this consumer",
    )

    order = landscape.create_order()
    screened = landscape.screen(order["id"])
    assert_order_dimensions(screened, compliance_status="OVERRIDE_PENDING")
    assert_rejection(screened, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")
    assert screened["override_applied"] is False
    assert _ledger_for_order(landscape, order["id"]) == []

    exception = landscape.raise_exception(
        order["id"], "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED",
        justification="State board granted a written one-time allowance",
    )
    assert landscape.read_winery()["open_exception_count"] == 1

    decided = validate_success(
        api.decide_compliance_exception(
            exception["id"],
            f.exception_decision_payload(
                "APPROVED", "Written allowance filed under TX-ALW-88"
            ),
            landscape.officer_b,
        ),
        expected_status=200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == "officer_b"
    assert decided["decision_note"] == "Written allowance filed under TX-ALW-88"
    assert_instant_equals(decided["decided_at"], CLOCK_DEFAULT_CANONICAL)

    cleared = landscape.read_order(order["id"])
    assert_order_dimensions(cleared, compliance_status="CLEARED")
    assert cleared["override_applied"] is True
    assert cleared["rejection_error_id"] is None
    assert_instant_equals(cleared["cleared_at"], CLOCK_DEFAULT_CANONICAL)

    rows = _ledger_for_order(landscape, order["id"])
    assert len(rows) == 1
    assert_ledger_entry(
        rows[0], event_type="SHIPMENT_ACCEPTED", liters=4.500, state_code="TX",
        order_id=order["id"],
    )

    consumer = landscape.read_consumer()
    assert_liters(consumer["rolling_liters_by_state"]["TX"], 29.500, "rolling TX liters")
    assert_liters(
        consumer["rolling_liters_settled_by_state"]["TX"], 25.000, "settled TX liters"
    )
    assert consumer["denied_exception_count"] == 0
    assert consumer["risk_score_screening"] == 27
    assert consumer["screening_tier"] == "STANDARD"

    winery = landscape.read_winery()
    assert_cents(winery["excise_accrued_cents"], 211, "excise_accrued_cents")
    assert winery["open_exception_count"] == 0

    validate_error(
        api.decide_compliance_exception(
            exception["id"], f.exception_decision_payload("DENIED"),
            landscape.officer_b,
        ),
        "ERR_EXCEPTION_ALREADY_DECIDED", expected_status=409,
    )


# ---------------------------------------------------------------------------
# CarrierEnrollment: APPROVED -> SUSPENDED by supersession
# ---------------------------------------------------------------------------
def test_a_second_enrollment_for_the_same_program_supersedes_the_first(api, landscape):
    """The system demotes the incumbent, and the winery is left with none live.

    "at most one enrollment per winery-and-program pair may be live at a time, so
    any enrollment the winery already holds for the same `carrier_program_id` in
    `PENDING` or `APPROVED` is moved by the system to `SUSPENDED` as part of the
    same call, and `Winery.version` increments by 1." (PRD 3.3)

    "A new enrollment opens in `status` `PENDING` with `approved_at` and
    `decided_by_user_id` both null." (PRD 3.3)

    "The named enrollment must be in `APPROVED` status and must belong to the
    order's own winery, and the enrolled program's `states_served` must contain
    the order's `ship_to_state_code`; a suspended or foreign enrollment, or a
    program that does not serve the destination, is refused with
    `ERR_CARRIER_NOT_ENROLLED`." (PRD 3.7)

    Design: Corner/state_machines/a_second_enrollment_for_the_same_program_supersedes_the_first
    """
    order = landscape.create_order()
    landscape.screen(order["id"])
    winery_version_before = landscape.winery_version()

    second = validate_success(
        api.create_carrier_enrollment(
            f.carrier_enrollment_payload(
                landscape.winery_id, landscape.program_id, winery_version_before,
                account_number="ACCT-2",
            ),
            landscape.operator,
        ),
        expected_status=201,
    )
    assert second["status"] == "PENDING"
    assert second["account_number"] == "ACCT-2"
    assert second["approved_at"] is None

    incumbent = validate_success(
        api.get_carrier_enrollment(landscape.enrollment_id, OFFICER_A),
        expected_status=200,
    )
    assert incumbent["status"] == "SUSPENDED"

    listed, _meta = _rows(api.list_carrier_enrollments(OFFICER_A, {"limit": 100}))
    mine = [row for row in listed if row["winery_id"] == landscape.winery_id]
    assert len(mine) == 2
    assert [row for row in mine if row["status"] == "APPROVED"] == []

    assert landscape.read_winery()["version"] == winery_version_before + 1

    validate_error(
        api.create_shipment(
            f.shipment_payload(order["id"], landscape.enrollment_id),
            landscape.operator,
        ),
        "ERR_CARRIER_NOT_ENROLLED", expected_status=422,
    )


# ---------------------------------------------------------------------------
# ClubSubscription: WEATHER_HELD -> ACTIVE performed by the run itself
# ---------------------------------------------------------------------------
def test_club_run_releases_a_lapsed_weather_hold_and_then_ships_it(api, landscape):
    """A lapsed hold is released by the run, and the member ships in that run.

    "if its `hold_release_date` falls on or before the `run_date`, the hold has
    lapsed, so the system performs the `WEATHER_HELD` → `ACTIVE` release itself —
    with the same field clearing as a manual release, including copying
    `hold_release_date` into `last_hold_release_date` — and the subscription then
    participates in the very same run" (PRD 3.8)

    "If the generated order landed in `CLEARED` or in `OVERRIDE_PENDING`,
    `next_run_date` is advanced by the subscription's `cadence`. Advancing a
    `MONTHLY` cadence means the same day-of-month one month later" (PRD 3.8)

    "the run creates an order for that subscription's consumer and winery with
    `club_subscription_id` set, with `ship_to_address_line`, `ship_to_state_code`
    and `ship_to_zip` copied from the consumer's default address" (PRD 3.8)

    "Note carefully that the run does **not** touch `consumed_shipments` on
    either branch: a cleared order already incremented that counter as part of
    its own clearance side effects" (PRD 3.8)

    Design: Corner/state_machines/club_run_releases_a_lapsed_weather_hold_and_then_ships_it
    """
    subscription = landscape.create_subscription(next_run_date="2026-08-01")

    held = validate_success(
        api.place_weather_hold(
            subscription["id"],
            f.weather_hold_payload("2026-07-20", "2026-07-25", "WEATHER_HEAT"),
            landscape.operator,
        ),
        expected_status=200,
    )
    assert held["status"] == "WEATHER_HELD"
    assert held["hold_release_date"] == "2026-07-25"
    assert held["next_run_date"] == "2026-08-01"

    run = landscape.club_run("2026-08-01")
    assert run["generated_count"] == 1
    assert run["skipped_count"] == 0
    assert run["skipped_subscription_ids"] == []
    assert len(run["generated_order_ids"]) == 1

    stored = landscape.read_subscription(subscription["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["hold_start_date"] is None
    assert stored["hold_release_date"] is None
    assert stored["hold_reason"] is None
    assert stored["last_hold_release_date"] == "2026-07-25"
    assert stored["next_run_date"] == "2026-09-01"
    assert stored["consumed_shipments"] == 1
    assert stored["remaining_allotment"] == 11
    assert stored["missed_run_count"] == 0

    generated = landscape.read_order(run["generated_order_ids"][0])
    assert_order_dimensions(generated, compliance_status="CLEARED")
    assert generated["club_subscription_id"] == subscription["id"]
    assert_cents(generated["shipping_discount_cents"], 623, "shipping_discount_cents")
    assert_cents(generated["shipping_cents"], 1867, "shipping_cents")
    assert_cents(
        generated["compliance_handling_fee_cents"], 900,
        "compliance_handling_fee_cents",
    )
    assert_cents(generated["total_cents"], 20019, "total_cents")
    assert generated["ship_to_state_code"] == "TX"
    assert generated["ship_to_zip"] == "78701"

    consumer_rows = [
        row for row in landscape.ledger_rows()
        if row.get("consumer_id") == landscape.consumer_id
    ]
    assert len(consumer_rows) == 1
    assert_ledger_entry(
        consumer_rows[0], event_type="SHIPMENT_ACCEPTED", liters=4.500,
        state_code="TX",
    )
