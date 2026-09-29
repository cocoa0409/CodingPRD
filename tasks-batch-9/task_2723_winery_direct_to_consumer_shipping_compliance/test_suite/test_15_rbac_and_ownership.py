"""Role-based access control, ownership scoping and duty segregation.

Every test here probes the identity gates of PRD §2.1 and the fixed evaluation
order of PRD §2.9: header presence first, then role authorization, then ownership
scoping, with the two segregation-of-duties pairs and the reserved
compliance-reinstatement authority sitting further down the same ladder.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_instant_equals,
    assert_liters,
    assert_order_dimensions,
    assert_rejection,
)
from test_helpers.constants import ROLE_COMPLIANCE_OFFICER
from test_helpers.fixtures import (
    append_manual_adjustment,
    create_consumer,
    create_winery,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    CARRIER,
    OFFICER_A,
    OFFICER_A_USER_ID,
    OFFICER_B,
    OFFICER_B_USER_ID,
    headers_for_role,
    make_carrier_headers,
    make_consumer_headers,
    make_winery_operator_headers,
)

JSON_CONTENT_TYPE = {"Content-Type": "application/json"}


def _identity_headers(user_id=None, role=None):
    """Build request headers, omitting whichever identity header is None."""
    built = dict(JSON_CONTENT_TYPE)
    if user_id is not None:
        built["X-User-ID"] = user_id
    if role is not None:
        built["X-User-Role"] = role
    return built


# ---------------------------------------------------------------------------
# Missing headers are 401; a wrong role on the same call is 403
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "user_id, role",
    [
        pytest.param(OFFICER_A_USER_ID, None, id="role_header_absent"),
        pytest.param(None, ROLE_COMPLIANCE_OFFICER, id="id_header_absent"),
        pytest.param(None, None, id="both_headers_absent"),
    ],
)
def test_screening_without_both_identity_headers_is_unauthenticated(
    api, landscape, user_id, role
):
    """A screen call missing either identity header is refused before anything else.

    "Every request to the API — without exception, including the logical-clock
    endpoint — must carry two headers." "If either header is absent or present but
    empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any
    other processing occurs." "This is the first check the server performs on any
    request." (PRD 2.1)

    Design: Corner/rbac/a_missing_identity_header_is_unauthenticated_while_a_wrong_role_is_unauthorized
    """
    order = landscape.create_order()

    response = api.screen_order(
        order["id"], {}, _identity_headers(user_id, role)
    )
    validate_error(response, "ERR_UNAUTHENTICATED", 401)

    unchanged = landscape.read_order(order["id"])
    assert_order_dimensions(unchanged, "DRAFT", "UNFULFILLED")
    assert unchanged["rejection_error_id"] is None
    assert unchanged["cleared_at"] is None


@pytest.mark.parametrize(
    "probe",
    ["undeclared_role_string", "consumer", "carrier_agent"],
)
def test_a_role_not_listed_on_the_screen_endpoint_is_unauthorized(
    api, landscape, probe
):
    """An undeclared role and a declared-but-unlisted role are both 403.

    "If `X-User-Role` is not one of these five strings, or is a valid role that is
    not listed among the authorized roles of the endpoint being called, the request
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." "This check runs immediately
    after the presence check on the two headers." (PRD 2.1)

    Design: Corner/rbac/a_missing_identity_header_is_unauthenticated_while_a_wrong_role_is_unauthorized
    """
    order = landscape.create_order()

    if probe == "undeclared_role_string":
        headers = headers_for_role("StateAuditor", "auditor_1")
    elif probe == "consumer":
        headers = make_consumer_headers(landscape.consumer_id)
    else:
        headers = make_carrier_headers("agent_1")

    response = api.screen_order(order["id"], {}, headers)
    validate_error(response, "ERR_UNAUTHORIZED", 403)

    unchanged = landscape.read_order(order["id"])
    assert_order_dimensions(unchanged, "DRAFT", "UNFULFILLED")
    assert unchanged["rejection_error_id"] is None


def test_identity_gate_refusals_never_run_the_screening_ladder(api, landscape):
    """Six identity refusals leave the order in DRAFT; the authorized call clears it.

    "**Screening never returns an error envelope.**" (PRD 2.9) "Recall from §2.9 that
    a screen which *runs* always answers HTTP 200 with the order body; a failing
    check is recorded in `rejection_error_id`, never returned as an error envelope."
    (PRD 3.6) "The full evaluation order, from first to last, is: header presence
    (`ERR_UNAUTHENTICATED`), role authorization (`ERR_UNAUTHORIZED`), ownership
    scoping (`ERR_FORBIDDEN_RESOURCE_OWNER`), path-identifier existence (the 404
    family), request-body shape (`ERR_INVALID_REQUEST`), body foreign-key existence
    (the 404 family again), optimistic concurrency (`ERR_STALE_VERSION`),
    state-transition legality (the 409 family: `ERR_INVALID_STATE_TRANSITION`,
    `ERR_ORDER_ALREADY_SCREENED`, `ERR_ORDER_NOT_CLEARED`,
    `ERR_EXCEPTION_ALREADY_DECIDED`, `ERR_ENROLLMENT_ALREADY_DECIDED`,
    `ERR_SHIPMENT_NOT_ACTIVE`), winery operating status (`ERR_WINERY_SUSPENDED`),
    compliance-reinstatement authority (`ERR_COMPLIANCE_REINSTATE_FORBIDDEN`),
    segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and only then the domain
    rules of §3." (PRD 2.9)

    Design: Corner/rbac/a_missing_identity_header_is_unauthenticated_while_a_wrong_role_is_unauthorized
    """
    order = landscape.create_order()

    unauthenticated = [
        _identity_headers(OFFICER_A_USER_ID, None),
        _identity_headers(None, ROLE_COMPLIANCE_OFFICER),
        _identity_headers(None, None),
    ]
    for headers in unauthenticated:
        validate_error(
            api.screen_order(order["id"], {}, headers), "ERR_UNAUTHENTICATED", 401
        )

    unauthorized = [
        headers_for_role("StateAuditor", "auditor_1"),
        make_consumer_headers(landscape.consumer_id),
        make_carrier_headers("agent_1"),
    ]
    for headers in unauthorized:
        validate_error(
            api.screen_order(order["id"], {}, headers), "ERR_UNAUTHORIZED", 403
        )

    frozen = landscape.read_order(order["id"])
    assert_order_dimensions(frozen, "DRAFT", "UNFULFILLED")
    assert frozen["rejection_error_id"] is None
    assert frozen["cleared_at"] is None
    assert landscape.ledger_rows(order_id=order["id"]) == []
    assert landscape.read_winery()["excise_accrued_cents"] == 0

    screened = validate_success(
        api.screen_order(order["id"], {}, OFFICER_A), 200
    )
    assert_order_dimensions(screened, "CLEARED", "UNFULFILLED")


# ---------------------------------------------------------------------------
# Peer isolation between the two entity-backed roles
# ---------------------------------------------------------------------------
def test_a_consumer_cannot_touch_another_consumers_rows(api, landscape):
    """Bo is refused Ada's profile, order, volume summary and order creation.

    "When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting
    `Consumer`; ownership checks compare `Consumer.id` itself, `Order.consumer_id`,
    `ClubSubscription.consumer_id`, or `VolumeLedgerEntry.consumer_id` to
    `X-User-ID`." "A mismatch on either family — a consumer reaching another
    consumer's order, subscription, ledger entry or profile, or a winery operator
    reaching another winery's permit, enrollment, order, shipment, subscription or
    remittance — is rejected with `ERR_FORBIDDEN_RESOURCE_OWNER` (HTTP 403)." (PRD 2.1)

    Design: Corner/rbac/a_consumer_cannot_touch_another_consumers_rows_and_a_winery_cannot_touch_another_winerys
    """
    bo = create_consumer(
        api,
        full_name="Bo Buyer",
        email="bo@example.com",
        birthdate="1979-05-05",
        address_line="8 Oak Rd",
        city="Austin",
        state_code="TX",
        zip_code="78701",
    )
    bo_headers = make_consumer_headers(bo["id"])
    ada_headers = landscape.buyer

    order = landscape.create_order()
    landscape.screen(order["id"])
    ada_version = landscape.consumer_version()

    validate_error(
        api.get_consumer(bo["id"], ada_headers), "ERR_FORBIDDEN_RESOURCE_OWNER", 403
    )
    validate_error(
        api.get_order(order["id"], bo_headers), "ERR_FORBIDDEN_RESOURCE_OWNER", 403
    )
    validate_error(
        api.get_volume_summary(
            landscape.consumer_id, bo_headers, {"state_code": "TX"}
        ),
        "ERR_FORBIDDEN_RESOURCE_OWNER",
        403,
    )
    impostor_payload = f.order_payload(
        landscape.winery_id, landscape.consumer_id, ada_version
    )
    validate_error(
        api.create_order(impostor_payload, bo_headers),
        "ERR_FORBIDDEN_RESOURCE_OWNER",
        403,
    )

    assert landscape.consumer_version() == ada_version
    rows, meta = validate_paginated(
        api.list_orders(OFFICER_A, {"consumer_id": landscape.consumer_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1

    own = validate_success(api.get_order(order["id"], ada_headers), 200)
    assert own["id"] == order["id"]


def test_a_winery_operator_cannot_touch_another_winerys_rows(api, landscape):
    """Estate 2 is refused Estate 1's label and Estate 1's renewal filing.

    "When `X-User-Role` is `WineryOperator`, `X-User-ID` is the `id` of the acting
    `Winery`; ownership checks on any resource that references a `Winery` compare the
    resource's foreign-key field to `X-User-ID`, which in practice means `Winery.id`
    itself, `StatePermit.winery_id`, `CarrierEnrollment.winery_id`,
    `Order.winery_id`, `ClubSubscription.winery_id`, `TaxRemittance.winery_id`, and —
    for a shipment, which holds no winery reference of its own — the `winery_id` of
    the order the shipment was drawn against." "This ownership check runs third,
    after role authorization and before any resource is looked up for existence."
    (PRD 2.1)

    Design: Corner/rbac/a_consumer_cannot_touch_another_consumers_rows_and_a_winery_cannot_touch_another_winerys
    """
    estate_2 = create_winery(
        api,
        name="Estate 2",
        ttb_permit_number="TTB-1002",
        home_state_code="OR",
        annual_production_gallons=40000,
    )
    impostor = make_winery_operator_headers(estate_2["id"])

    order = landscape.create_order()
    landscape.screen(order["id"])

    validate_error(
        api.create_shipment(
            f.shipment_payload(order["id"], landscape.enrollment_id), impostor
        ),
        "ERR_FORBIDDEN_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.file_permit_renewal(
            landscape.permit_id, f.file_renewal_payload("RN-9"), impostor
        ),
        "ERR_FORBIDDEN_RESOURCE_OWNER",
        403,
    )

    permit = landscape.read_permit()
    assert permit["status"] == "ACTIVE"
    assert permit["renewal_reference"] is None
    assert permit["renewal_filed_at"] is None

    shipment = validate_success(
        api.create_shipment(
            f.shipment_payload(order["id"], landscape.enrollment_id),
            landscape.operator,
        ),
        201,
    )
    assert shipment["status"] == "LABEL_CREATED"
    assert_order_dimensions(
        landscape.read_order(order["id"]), "CLEARED", "LABELED"
    )

    rows, meta = validate_paginated(
        api.list_shipments(OFFICER_A, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Segregation of duties on the two raise/decide and file/remit pairs
# ---------------------------------------------------------------------------
def test_the_officer_who_raised_an_exception_cannot_decide_it(api, landscape):
    """officer_a is refused its own exception; officer_b lands the same decision.

    "The `ComplianceOfficer` who decides a compliance exception must not be the same
    `X-User-ID` that is recorded in that exception's `requested_by_user_id`, and the
    `ComplianceOfficer` who records payment of a tax remittance must not be the same
    `X-User-ID` recorded in that remittance's `filed_by_user_id`." "Either violation
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." "Note that this is a
    check on the identifier, not on the role: two different officers are always
    acceptable, and the same officer is never acceptable." (PRD 2.1) "An **`OPEN` →
    `APPROVED`** decision moves the order `OVERRIDE_PENDING` → `CLEARED`, sets its
    `override_applied` flag to true, clears its `rejection_error_id` to null, and
    stamps `cleared_at` from the logical clock." (PRD 3.6)

    Design: Corner/rbac/the_officer_who_raised_an_exception_cannot_decide_it_and_the_filer_cannot_remit
    """
    order_a = landscape.create_order()
    landscape.screen(order_a["id"])
    append_manual_adjustment(
        api,
        landscape.consumer_id,
        landscape.winery_id,
        21.000,
        occurred_at="2026-07-01T00:00:00Z",
        reason="Pre-platform TX volume",
    )
    order_b = landscape.create_order()
    referred = landscape.screen(order_b["id"])
    assert_order_dimensions(referred, "OVERRIDE_PENDING", "UNFULFILLED")
    assert_rejection(referred, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")

    exception = landscape.raise_exception(
        order_b["id"],
        "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED",
        justification="State board granted a written one-time allowance",
    )
    assert exception["requested_by_user_id"] == OFFICER_A_USER_ID
    assert landscape.read_winery()["open_exception_count"] == 1

    validate_error(
        api.decide_compliance_exception(
            exception["id"],
            f.exception_decision_payload("APPROVED", "Self-approving on purpose"),
            OFFICER_A,
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    untouched = landscape.read_exception(exception["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["decided_at"] is None
    assert untouched["decided_by_user_id"] is None
    assert landscape.read_winery()["open_exception_count"] == 1
    assert_order_dimensions(
        landscape.read_order(order_b["id"]), "OVERRIDE_PENDING", "UNFULFILLED"
    )

    decided = validate_success(
        api.decide_compliance_exception(
            exception["id"],
            f.exception_decision_payload(
                "APPROVED", "Independent review of the written allowance"
            ),
            OFFICER_B,
        ),
        200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == OFFICER_B_USER_ID
    assert decided["requested_by_user_id"] == OFFICER_A_USER_ID

    overridden = landscape.read_order(order_b["id"])
    assert_order_dimensions(overridden, "CLEARED", "UNFULFILLED")
    assert overridden["override_applied"] is True
    assert overridden["rejection_error_id"] is None

    accepted = [
        row
        for row in landscape.ledger_rows(order_id=order_b["id"])
        if row["event_type"] == "SHIPMENT_ACCEPTED"
    ]
    assert len(accepted) == 1
    assert_liters(accepted[0]["liters"], 4.500, "liters")
    assert_liters(
        landscape.read_consumer()["rolling_liters_by_state"]["TX"],
        30.000,
        "rolling_liters_by_state.TX",
    )
    assert landscape.read_winery()["open_exception_count"] == 0


def test_the_officer_who_filed_a_remittance_cannot_record_its_payment(api, landscape):
    """officer_a is refused payment of its own filing; officer_b remits it.

    "And this is the second place segregation of duties bites: the officer recording
    payment must not be the officer whose `X-User-ID` is stored in
    `filed_by_user_id`, or the call is refused with `ERR_SEGREGATION_OF_DUTIES`."
    "Recording payment moves the remittance `FILED` → `REMITTED` and captures the
    state's confirmation reference in `payment_reference`, stamping `remitted_at`
    from the logical clock and `remitted_by_user_id` from the acting officer's
    `X-User-ID`." (PRD 3.9)

    Design: Corner/rbac/the_officer_who_raised_an_exception_cannot_decide_it_and_the_filer_cannot_remit
    """
    order = landscape.create_order()
    landscape.screen(order["id"])

    set_clock(api, "2026-09-01T00:00:00Z")
    remittance = landscape.open_remittance(
        "TX", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert remittance["shipment_count"] == 1

    filed = validate_success(
        api.file_remittance(remittance["id"], {}, OFFICER_A), 200
    )
    assert filed["status"] == "FILED"
    assert filed["filed_by_user_id"] == OFFICER_A_USER_ID

    validate_error(
        api.remit_remittance(
            remittance["id"], f.remit_payload("PAY-SELF"), OFFICER_A
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    untouched = landscape.read_remittance(remittance["id"])
    assert untouched["status"] == "FILED"
    assert untouched["remitted_at"] is None
    assert untouched["remitted_by_user_id"] is None

    remitted = validate_success(
        api.remit_remittance(remittance["id"], f.remit_payload("PAY-1"), OFFICER_B),
        200,
    )
    assert remitted["status"] == "REMITTED"
    assert remitted["remitted_by_user_id"] == OFFICER_B_USER_ID
    assert remitted["filed_by_user_id"] == OFFICER_A_USER_ID
    assert remitted["payment_reference"] == "PAY-1"
    assert_instant_equals(remitted["remitted_at"], "2026-09-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Compliance reinstatement is reserved to a ComplianceOfficer
# ---------------------------------------------------------------------------
def _compliance_suspended_subscription(landscape):
    """Suspend one club subscription through the permit-revocation cascade."""
    subscription = landscape.create_subscription(
        next_run_date="2026-08-01", annual_allotment=6
    )
    run = landscape.club_run("2026-08-01")
    assert run["generated_count"] == 1
    order_id = run["generated_order_ids"][0]
    assert_order_dimensions(landscape.read_order(order_id), "CLEARED", "UNFULFILLED")

    advanced = landscape.read_subscription(subscription["id"])
    assert advanced["status"] == "ACTIVE"
    assert advanced["next_run_date"] == "2026-09-01"
    assert advanced["consumed_shipments"] == 1
    assert advanced["missed_run_count"] == 0

    landscape.revoke_permit(reason="State board suspended the shipper licence")

    suspended = landscape.read_subscription(subscription["id"])
    assert suspended["status"] == "SUSPENDED_COMPLIANCE"
    assert suspended["next_run_date"] is None
    assert suspended["missed_run_count"] == 0
    assert_order_dimensions(
        landscape.read_order(order_id), "SUSPENDED_PERMIT", "UNFULFILLED"
    )
    assert landscape.read_winery()["suspended_subscription_count"] == 1
    return subscription["id"], order_id


def test_a_winery_operator_cannot_lift_a_compliance_suspension(api, landscape):
    """The operator's reinstatement attempt is refused and changes nothing.

    "Releasing a `SUSPENDED_COMPLIANCE` subscription is a different act entirely: it
    is a compliance reinstatement, it requires `reset_missed_runs` to be true, and it
    is **reserved to a `ComplianceOfficer`** — a `WineryOperator` attempting it is
    refused with `ERR_COMPLIANCE_REINSTATE_FORBIDDEN` (HTTP 403)." (PRD 3.8)
    "Separately, authority over compliance suspensions is reserved: only a
    `ComplianceOfficer` may lift a club subscription that the system suspended for
    compliance reasons, and a `WineryOperator` attempting it is refused with
    `ERR_COMPLIANCE_REINSTATE_FORBIDDEN` (HTTP 403)." (PRD 2.1)

    Design: Corner/rbac/a_winery_operator_cannot_lift_a_compliance_suspension_it_did_not_impose
    """
    subscription_id, order_id = _compliance_suspended_subscription(landscape)
    winery_version_before = landscape.winery_version()

    validate_error(
        api.release_hold(
            subscription_id, f.release_hold_payload(True), landscape.operator
        ),
        "ERR_COMPLIANCE_REINSTATE_FORBIDDEN",
        403,
    )

    untouched = landscape.read_subscription(subscription_id)
    assert untouched["status"] == "SUSPENDED_COMPLIANCE"
    assert untouched["next_run_date"] is None
    assert untouched["consumed_shipments"] == 1
    assert landscape.read_winery()["suspended_subscription_count"] == 1
    assert landscape.winery_version() == winery_version_before
    assert_order_dimensions(
        landscape.read_order(order_id), "SUSPENDED_PERMIT", "UNFULFILLED"
    )


def test_a_compliance_officer_reinstatement_unwinds_only_the_subscription(
    api, landscape
):
    """The officer's reinstatement lands, resets the count and rejoins the schedule.

    "A reinstatement puts `missed_run_count` back to 0, sets `next_run_date` to the
    logical clock date so the subscription rejoins the schedule immediately,
    recomputes the winery's `suspended_subscription_count`, and increments
    `Winery.version` by 1." (PRD 3.8) "Revocation is the most consequential act in
    this section, reserved to a `ComplianceOfficer`, available from `PENDING`,
    `ACTIVE`, `RENEWAL_FILED` and `EXPIRED` alike, and terminal — a `REVOKED` permit
    can never move again, and attempting to revoke one is refused with
    `ERR_INVALID_STATE_TRANSITION`." (PRD 3.2)

    Design: Corner/rbac/a_winery_operator_cannot_lift_a_compliance_suspension_it_did_not_impose
    """
    subscription_id, order_id = _compliance_suspended_subscription(landscape)
    winery_version_before = landscape.winery_version()

    reinstated = validate_success(
        api.release_hold(subscription_id, f.release_hold_payload(True), OFFICER_A), 200
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["missed_run_count"] == 0
    assert reinstated["next_run_date"] == "2026-08-01"
    assert reinstated["consumed_shipments"] == 1
    assert reinstated["remaining_allotment"] == 5

    winery = landscape.read_winery()
    assert winery["suspended_subscription_count"] == 0
    assert winery["version"] == winery_version_before + 1

    assert_order_dimensions(
        landscape.read_order(order_id), "SUSPENDED_PERMIT", "UNFULFILLED"
    )
    assert landscape.read_permit()["status"] == "REVOKED"


# ---------------------------------------------------------------------------
# One exclusive operation per role, attempted from a tempting neighbour
# ---------------------------------------------------------------------------
def _cleared_and_labeled(landscape):
    """A CLEARED 6 x 750 ml order carrying one LABEL_CREATED shipment."""
    order = landscape.create_order()
    screened = landscape.screen(order["id"])
    assert_order_dimensions(screened, "CLEARED", "UNFULFILLED")
    shipment = landscape.label(order["id"])
    assert shipment["status"] == "LABEL_CREATED"
    return order, shipment


EXCLUSIVE_PROBES = {
    "platform_admin_filing_a_state_permit": lambda api, scape, order, shipment: (
        api.create_state_permit(
            f.state_permit_payload(
                scape.winery_id,
                permit_number="TX-DTC-9",
                permit_type="WINE_SHIPPER",
                effective_date="2027-01-01",
                expiration_date="2027-12-31",
            ),
            ADMIN,
        )
    ),
    "platform_admin_recording_an_id_verification": lambda api, scape, order, shipment: (
        api.verify_consumer_id(
            scape.consumer_id, f.id_verification_payload("DATABASE"), ADMIN
        )
    ),
    "platform_admin_screening_an_order": lambda api, scape, order, shipment: (
        api.screen_order(order["id"], {}, ADMIN)
    ),
    "compliance_officer_registering_a_winery": lambda api, scape, order, shipment: (
        api.create_winery(
            f.winery_payload(
                name="Estate 3",
                ttb_permit_number="TTB-1003",
                home_state_code="WA",
                annual_production_gallons=9000,
            ),
            OFFICER_A,
        )
    ),
    "compliance_officer_labelling_a_shipment": lambda api, scape, order, shipment: (
        api.create_shipment(
            f.shipment_payload(order["id"], scape.enrollment_id), OFFICER_A
        )
    ),
    "winery_operator_posting_a_carrier_scan": lambda api, scape, order, shipment: (
        api.scan_shipment(shipment["id"], f.pickup_scan(), scape.operator)
    ),
    "carrier_agent_creating_an_order": lambda api, scape, order, shipment: (
        api.create_order(
            f.order_payload(
                scape.winery_id, scape.consumer_id, scape.consumer_version()
            ),
            CARRIER,
        )
    ),
    "consumer_listing_every_consumer": lambda api, scape, order, shipment: (
        api.list_consumers(scape.buyer, {"state_code": "TX"})
    ),
}


@pytest.mark.parametrize("probe", sorted(EXCLUSIVE_PROBES))
def test_an_exclusive_operation_refuses_every_other_role(api, landscape, probe):
    """Each role's exclusive operation is refused to an adjacent, tempting role.

    "If `X-User-Role` is not one of these five strings, or is a valid role that is not
    listed among the authorized roles of the endpoint being called, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)." "`PlatformAdmin` is the platform
    operator; it seeds wineries, state rules, prohibited ZIPs, carrier programs and
    consumers, drives the logical clock, and never decides a compliance outcome."
    "`CarrierAgent` is the shipping carrier; it decides winery enrollments and posts
    the scan events that drive fulfillment, and can never create an order, screen one,
    produce a label or touch tax." (PRD 2.1)

    Design: Corner/rbac/cross_role_attempts_on_another_roles_exclusive_operations_are_unauthorized
    """
    order, shipment = _cleared_and_labeled(landscape)
    response = EXCLUSIVE_PROBES[probe](api, landscape, order, shipment)
    validate_error(response, "ERR_UNAUTHORIZED", 403)


def test_the_refused_cross_role_attempts_change_nothing(api, landscape):
    """Eight role refusals in a row leave every touched row exactly as it was.

    "This check runs immediately after the presence check on the two headers."
    (PRD 2.1) "Because a single request can violate several rules at once, the outcome
    the caller sees is determined entirely by which rule the server checks first."
    (PRD 2.9)

    Design: Corner/rbac/cross_role_attempts_on_another_roles_exclusive_operations_are_unauthorized
    """
    order, shipment = _cleared_and_labeled(landscape)
    consumer_version_before = landscape.consumer_version()

    for probe in sorted(EXCLUSIVE_PROBES):
        validate_error(
            EXCLUSIVE_PROBES[probe](api, landscape, order, shipment),
            "ERR_UNAUTHORIZED",
            403,
        )

    permits, permit_meta = validate_paginated(
        api.list_state_permits(OFFICER_A, {"winery_id": landscape.winery_id})
    )
    assert permit_meta["total_count"] == 1
    assert permits[0]["id"] == landscape.permit_id

    consumer = landscape.read_consumer()
    assert consumer["id_verification_method"] == "DOCUMENT"
    assert consumer["version"] == consumer_version_before

    assert landscape.read_shipment(shipment["id"])["status"] == "LABEL_CREATED"
    # The label of _cleared_and_labeled already moved the order UNFULFILLED ->
    # LABELED (PRD 3.7); the eight refusals must leave it exactly there.
    assert_order_dimensions(landscape.read_order(order["id"]), "CLEARED", "LABELED")

    orders, order_meta = validate_paginated(
        api.list_orders(OFFICER_A, {"winery_id": landscape.winery_id})
    )
    assert order_meta["total_count"] == 1

    wineries, winery_meta = validate_paginated(api.list_wineries(ADMIN))
    assert winery_meta["total_count"] == 1


def test_the_rightful_role_lands_the_call_that_the_others_were_refused(api, landscape):
    """The carrier's own scan and the consumer's own profile read both succeed.

    "`CarrierAgent` is the shipping carrier; it decides winery enrollments and posts
    the scan events that drive fulfillment, and can never create an order, screen one,
    produce a label or touch tax." "`Consumer` is the wine buyer; it may place its own
    orders and read its own records." (PRD 2.1) "A **`PICKUP`** scan moves the shipment
    `LABEL_CREATED` → `IN_TRANSIT` and moves the order from `LABELED` to `IN_TRANSIT`
    with it." (PRD 3.7)

    Design: Corner/rbac/cross_role_attempts_on_another_roles_exclusive_operations_are_unauthorized
    """
    order, shipment = _cleared_and_labeled(landscape)

    scanned = validate_success(
        api.scan_shipment(shipment["id"], f.pickup_scan(), CARRIER), 200
    )
    assert scanned["status"] == "IN_TRANSIT"
    assert landscape.read_shipment(shipment["id"])["status"] == "IN_TRANSIT"
    assert_order_dimensions(landscape.read_order(order["id"]), "CLEARED", "IN_TRANSIT")

    own_profile = validate_success(
        api.get_consumer(landscape.consumer_id, landscape.buyer), 200
    )
    assert own_profile["id"] == landscape.consumer_id
