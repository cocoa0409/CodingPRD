"""Composite fixtures for the Winery DTC API.

The harness restarts the server and empties the database before every single
test, so every fixture here builds its preconditions from scratch through the
public API.  Nothing is shared between tests.

The building blocks are ordinary functions so a test that needs a variation can
call them directly; the pytest fixtures at the bottom of the file wrap the most
frequently needed arrangements.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import DtcApiClient
from .constants import (
    CARRIER_PROGRAM_GSO_TX,
    CLOCK_STARTUP_DEFAULT,
    CONSUMER_ADA,
    PERMIT_TX_2026,
    STATE_RULE_NM,
    STATE_RULE_TX,
    WINERY_ESTATE_1,
)
from . import factories as f
from .test_users import (
    ADMIN,
    CARRIER,
    OFFICER_A,
    OFFICER_B,
    make_consumer_headers,
    make_winery_operator_headers,
)


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(api, current_utc=CLOCK_STARTUP_DEFAULT, headers=ADMIN):
    """Move the logical clock (PRD §2.4)."""
    return get_success_data(api.set_clock(current_utc, headers))


def create_winery(api, headers=ADMIN, **overrides):
    payload = f.winery_payload(**overrides)
    return get_success_data(api.create_winery(payload, headers), 201)


def create_state_rule(api, headers=ADMIN, **overrides):
    payload = f.state_rule_payload(**overrides)
    return get_success_data(api.create_state_rule(payload, headers), 201)


def create_state_rule_nm(api, headers=ADMIN, **overrides):
    payload = f.state_rule_nm_payload(**overrides)
    return get_success_data(api.create_state_rule(payload, headers), 201)


def create_prohibited_zip(api, state_rule_id, headers=OFFICER_A, **overrides):
    payload = f.prohibited_zip_payload(**overrides)
    return get_success_data(
        api.create_prohibited_zip(state_rule_id, payload, headers), 201
    )


def create_carrier_program(api, headers=ADMIN, **overrides):
    payload = f.carrier_program_payload(**overrides)
    return get_success_data(api.create_carrier_program(payload, headers), 201)


def create_consumer(api, headers=ADMIN, **overrides):
    payload = f.consumer_payload(**overrides)
    return get_success_data(api.create_consumer(payload, headers), 201)


def verify_consumer(api, consumer_id, method="DOCUMENT", headers=OFFICER_A):
    return get_success_data(
        api.verify_consumer_id(consumer_id, f.id_verification_payload(method), headers)
    )


def create_verified_consumer(api, headers=ADMIN, method="DOCUMENT", **overrides):
    consumer = create_consumer(api, headers=headers, **overrides)
    verify_consumer(api, consumer["id"], method=method)
    return consumer


def winery_version(api, winery_id, headers=ADMIN):
    """Read the winery's current version for the OCC guard of PRD §2.6."""
    return get_success_data(api.get_winery(winery_id, headers))["version"]


def consumer_version(api, consumer_id, headers=OFFICER_A):
    """Read the consumer's current version for the OCC guard of PRD §2.6."""
    return get_success_data(api.get_consumer(consumer_id, headers))["version"]


def create_permit(api, winery_id, headers=OFFICER_A, **overrides):
    payload = f.state_permit_payload(winery_id, **overrides)
    return get_success_data(api.create_state_permit(payload, headers), 201)


def activate_permit(api, permit_id, headers=OFFICER_A):
    return get_success_data(api.activate_state_permit(permit_id, {}, headers))


def create_active_permit(api, winery_id, headers=OFFICER_A, **overrides):
    permit = create_permit(api, winery_id, headers=headers, **overrides)
    activate_permit(api, permit["id"], headers=headers)
    return permit


def create_enrollment(api, winery_id, carrier_program_id, headers=None,
                      account_number="ACCT-1", expected_winery_version=None):
    if expected_winery_version is None:
        expected_winery_version = winery_version(api, winery_id)
    payload = f.carrier_enrollment_payload(
        winery_id, carrier_program_id, expected_winery_version,
        account_number=account_number,
    )
    operator = headers or make_winery_operator_headers(winery_id)
    return get_success_data(api.create_carrier_enrollment(payload, operator), 201)


def decide_enrollment(api, enrollment_id, decision, note=None, headers=CARRIER):
    return get_success_data(
        api.decide_carrier_enrollment(
            enrollment_id, f.enrollment_decision_payload(decision, note), headers
        )
    )


def create_approved_enrollment(api, winery_id, carrier_program_id, **kwargs):
    enrollment = create_enrollment(api, winery_id, carrier_program_id, **kwargs)
    decide_enrollment(api, enrollment["id"], "APPROVED")
    return enrollment


def append_manual_adjustment(api, consumer_id, winery_id, liters, headers=OFFICER_A,
                             **overrides):
    """Append a MANUAL_ADJUSTMENT ledger row (PRD §3.4)."""
    payload = f.manual_adjustment_payload(consumer_id, winery_id, liters, **overrides)
    return get_success_data(api.create_volume_ledger_entry(payload, headers), 201)


# ---------------------------------------------------------------------------
# The compliance landscape: winery, state, permit, carrier, consumer
# ---------------------------------------------------------------------------
class Landscape:
    """Everything upstream of screening, already standing.

    Holds the ids of the rows that PRD §3.1 to §3.4 require before an order can
    be assessed, together with the identity headers that own them.
    """

    def __init__(self, api, winery, state_rule, permit, program, enrollment,
                 consumer):
        self.api = api
        self.winery = winery
        self.state_rule = state_rule
        self.permit = permit
        self.program = program
        self.enrollment = enrollment
        self.consumer = consumer

        self.winery_id = winery["id"] if winery else None
        self.state_rule_id = state_rule["id"] if state_rule else None
        self.permit_id = permit["id"] if permit else None
        self.program_id = program["id"] if program else None
        self.enrollment_id = enrollment["id"] if enrollment else None
        self.consumer_id = consumer["id"] if consumer else None

        self.admin = ADMIN
        self.officer = OFFICER_A
        self.officer_b = OFFICER_B
        self.carrier = CARRIER
        self.operator = (
            make_winery_operator_headers(self.winery_id) if winery else None
        )
        self.buyer = make_consumer_headers(self.consumer_id) if consumer else None

    # -- reads ---------------------------------------------------------
    def read_winery(self, winery_id=None, headers=None):
        target = winery_id or self.winery_id
        return get_success_data(
            self.api.get_winery(target, headers or self.admin)
        )

    def read_consumer(self, consumer_id=None, headers=None):
        target = consumer_id or self.consumer_id
        return get_success_data(
            self.api.get_consumer(target, headers or self.officer)
        )

    def read_order(self, order_id, headers=None):
        return get_success_data(
            self.api.get_order(order_id, headers or self.officer)
        )

    def read_permit(self, permit_id=None, headers=None):
        target = permit_id or self.permit_id
        return get_success_data(
            self.api.get_state_permit(target, headers or self.officer)
        )

    def read_shipment(self, shipment_id, headers=None):
        return get_success_data(
            self.api.get_shipment(shipment_id, headers or self.officer)
        )

    def read_subscription(self, subscription_id, headers=None):
        return get_success_data(
            self.api.get_club_subscription(subscription_id, headers or self.officer)
        )

    def read_remittance(self, remittance_id, headers=None):
        return get_success_data(
            self.api.get_remittance(remittance_id, headers or self.officer)
        )

    def read_exception(self, exception_id, headers=None):
        return get_success_data(
            self.api.get_compliance_exception(exception_id, headers or self.officer)
        )

    def ledger_rows(self, headers=None, **filters):
        params = dict(filters)
        params.setdefault("limit", 100)
        response = self.api.list_volume_ledger_entries(headers or self.officer, params)
        return get_success_data(response)

    def volume_summary(self, consumer_id=None, state_code=None, headers=None):
        target = consumer_id or self.consumer_id
        params = {} if state_code is None else {"state_code": state_code}
        return get_success_data(
            self.api.get_volume_summary(target, headers or self.officer, params)
        )

    def consumer_version(self, consumer_id=None):
        return self.read_consumer(consumer_id)["version"]

    def winery_version(self, winery_id=None):
        return self.read_winery(winery_id)["version"]

    # -- writes --------------------------------------------------------
    def create_order(self, lines=None, headers=None, consumer_id=None,
                     winery_id=None, expected_consumer_version=None, **overrides):
        """Create an order, reading the consumer's current version first."""
        target_consumer = consumer_id or self.consumer_id
        target_winery = winery_id or self.winery_id
        if expected_consumer_version is None:
            expected_consumer_version = self.consumer_version(target_consumer)
        payload = f.order_payload(
            target_winery, target_consumer, expected_consumer_version,
            lines=lines, **overrides
        )
        return get_success_data(
            self.api.create_order(payload, headers or self.operator), 201
        )

    def screen(self, order_id, headers=None):
        """Screen an order; screening always answers HTTP 200 (PRD §2.9)."""
        return get_success_data(
            self.api.screen_order(order_id, {}, headers or self.officer), 200
        )

    def create_cleared_order(self, lines=None, **kwargs):
        order = self.create_order(lines=lines, **kwargs)
        return self.screen(order["id"])

    def label(self, order_id, enrollment_id=None, replacement_of_shipment_id=None,
              headers=None):
        payload = f.shipment_payload(
            order_id, enrollment_id or self.enrollment_id, replacement_of_shipment_id
        )
        return get_success_data(
            self.api.create_shipment(payload, headers or self.operator), 201
        )

    def scan(self, shipment_id, payload, headers=None):
        return get_success_data(
            self.api.scan_shipment(shipment_id, payload, headers or self.carrier)
        )

    def pickup(self, shipment_id):
        return self.scan(shipment_id, f.pickup_scan())

    def deliver(self, shipment_id, signed_by="Ada Buyer", signer_age_verified=True):
        return self.scan(
            shipment_id, f.delivered_scan(signed_by, signer_age_verified)
        )

    def return_to_sender(self, shipment_id):
        return self.scan(shipment_id, f.return_scan())

    def create_subscription(self, headers=None, consumer_id=None, winery_id=None,
                            **overrides):
        payload = f.club_subscription_payload(
            consumer_id or self.consumer_id, winery_id or self.winery_id, **overrides
        )
        return get_success_data(
            self.api.create_club_subscription(payload, headers or self.operator), 201
        )

    def club_run(self, run_date, winery_id=None, headers=None):
        payload = f.club_run_payload(winery_id or self.winery_id, run_date)
        return get_success_data(
            self.api.create_club_run(payload, headers or self.operator), 200
        )

    def open_remittance(self, state_code, period_start, period_end,
                        period_type="MONTHLY", basis="ACCRUAL_BASIS",
                        headers=None, **overrides):
        payload = f.remittance_payload(
            self.winery_id, state_code, period_start, period_end,
            period_type=period_type, basis=basis, **overrides
        )
        return get_success_data(
            self.api.create_remittance(payload, headers or self.officer), 201
        )

    def raise_exception(self, order_id, raised_rule, headers=None,
                        justification="Long-standing member in good standing"):
        payload = f.compliance_exception_payload(raised_rule, justification)
        return get_success_data(
            self.api.raise_compliance_exception(
                order_id, payload, headers or self.officer
            ),
            201,
        )

    def decide_exception(self, exception_id, decision, headers=None,
                         decision_note="Reviewed"):
        payload = f.exception_decision_payload(decision, decision_note)
        return get_success_data(
            self.api.decide_compliance_exception(
                exception_id, payload, headers or self.officer_b
            )
        )

    def revoke_permit(self, permit_id=None, reason="License revoked by the state board",
                      headers=None):
        target = permit_id or self.permit_id
        return get_success_data(
            self.api.revoke_state_permit(
                target, f.revoke_payload(reason), headers or self.officer
            )
        )


# ---------------------------------------------------------------------------
# Landscape builders
# ---------------------------------------------------------------------------
def build_landscape(api, clock=CLOCK_STARTUP_DEFAULT, state_rule_overrides=None,
                    winery_overrides=None, consumer_overrides=None,
                    program_overrides=None, permit_overrides=None,
                    activate_permit_row=True, approve_enrollment=True,
                    verify_consumer_id=True):
    """Stand up the whole pre-screening landscape.

    Winery Estate 1 (120000 gallons, so the small-producer credit of PRD §3.5
    applies), the TX state rule, a TX DIRECT_SHIPPER permit, the GSO carrier
    program with an adult-signature service code, an enrollment, and consumer
    Ada.  The flags let a caller stop short of activation, approval or
    verification so the arm that fails a gate can be built from the same code.
    """
    set_clock(api, clock)
    winery = create_winery(api, **(winery_overrides or {}))
    state_rule = create_state_rule(api, **(state_rule_overrides or {}))
    if activate_permit_row:
        permit = create_active_permit(api, winery["id"], **(permit_overrides or {}))
    else:
        permit = create_permit(api, winery["id"], **(permit_overrides or {}))
    program = create_carrier_program(api, **(program_overrides or {}))
    if approve_enrollment:
        enrollment = create_approved_enrollment(api, winery["id"], program["id"])
    else:
        enrollment = create_enrollment(api, winery["id"], program["id"])
    if verify_consumer_id:
        consumer = create_verified_consumer(api, **(consumer_overrides or {}))
    else:
        consumer = create_consumer(api, **(consumer_overrides or {}))
    return Landscape(api, winery, state_rule, permit, program, enrollment, consumer)


def build_landscape_without_permit(api, clock=CLOCK_STARTUP_DEFAULT,
                                   state_rule_overrides=None,
                                   winery_overrides=None,
                                   consumer_overrides=None,
                                   program_overrides=None):
    """The same landscape with no state permit filed at all."""
    set_clock(api, clock)
    winery = create_winery(api, **(winery_overrides or {}))
    state_rule = create_state_rule(api, **(state_rule_overrides or {}))
    program = create_carrier_program(api, **(program_overrides or {}))
    enrollment = create_approved_enrollment(api, winery["id"], program["id"])
    consumer = create_verified_consumer(api, **(consumer_overrides or {}))
    return Landscape(api, winery, state_rule, None, program, enrollment, consumer)


def build_bare_landscape(api, clock=CLOCK_STARTUP_DEFAULT, state_rule_overrides=None,
                         winery_overrides=None):
    """Only the clock, a winery and a state rule — no permit, carrier or consumer."""
    set_clock(api, clock)
    winery = create_winery(api, **(winery_overrides or {}))
    state_rule = create_state_rule(api, **(state_rule_overrides or {}))
    return Landscape(api, winery, state_rule, None, None, None, None)


def add_nm_state(api, landscape, activate=True, **rule_overrides):
    """Add the NM state rule and a matching permit to an existing landscape."""
    rule = create_state_rule_nm(api, **rule_overrides)
    permit = create_permit(
        api, landscape.winery_id, state_code="NM", permit_number="NM-DTC-1",
    )
    if activate:
        activate_permit(api, permit["id"])
    return rule, permit


def build_cleared_order(api, landscape=None, lines=None, **kwargs):
    """A CLEARED order sitting at UNFULFILLED (PRD §3.6 clearance chain)."""
    scape = landscape or build_landscape(api)
    order = scape.create_order(lines=lines, **kwargs)
    return scape, scape.screen(order["id"])


def build_labeled_order(api, landscape=None, lines=None, **kwargs):
    """A CLEARED order that already carries a LABEL_CREATED shipment."""
    scape, order = build_cleared_order(api, landscape, lines=lines, **kwargs)
    shipment = scape.label(order["id"])
    return scape, order, shipment


def build_in_transit_order(api, landscape=None, lines=None, **kwargs):
    """A CLEARED order whose shipment has been picked up (PRD §3.7)."""
    scape, order, shipment = build_labeled_order(api, landscape, lines=lines, **kwargs)
    scape.pickup(shipment["id"])
    return scape, order, shipment


def build_delivered_order(api, landscape=None, lines=None, **kwargs):
    """A DELIVERED order, eligible for a delivery-basis period (PRD §3.9)."""
    scape, order, shipment = build_in_transit_order(api, landscape, lines=lines,
                                                    **kwargs)
    scape.deliver(shipment["id"])
    return scape, order, shipment


def build_returned_order(api, landscape=None, lines=None, **kwargs):
    """A returned order: the compensating cascade of PRD §3.7 has fired."""
    scape, order, shipment = build_in_transit_order(api, landscape, lines=lines,
                                                    **kwargs)
    scape.return_to_sender(shipment["id"])
    return scape, order, shipment


def build_override_pending_order(api, landscape=None, seeded_liters=25.000,
                                 occurred_at="2026-07-15T00:00:00Z", lines=None):
    """An order parked in OVERRIDE_PENDING on the consumer volume limit.

    A back-dated manual adjustment eats the consumer's TX headroom, so the next
    order's total_liters pushes the rolling total past
    ``per_consumer_limit_liters`` and PRD §3.6 makes the failure overridable.

    The seed must leave less than the canonical 4.500 L of headroom: landing
    exactly on ``per_consumer_limit_liters`` clears, so 25.000 + 4.500 = 29.500
    breaches the 27.000 L TX limit while 22.500 + 4.500 would not.
    """
    scape = landscape or build_landscape(api)
    append_manual_adjustment(
        api, scape.consumer_id, scape.winery_id, seeded_liters,
        occurred_at=occurred_at,
    )
    order = scape.create_order(lines=lines)
    return scape, scape.screen(order["id"])


def build_elevated_consumer(api, landscape=None):
    """Drive a consumer to ``screening_tier`` ELEVATED through denied exceptions.

    Each DENIED compliance exception adds 15 points to ``risk_score_screening``
    (PRD §3.4) and PRD §3.6 makes the risk gate itself overridable, so a chain of
    denials is the way to reach the 50-point threshold.
    """
    scape = landscape or build_landscape(api)
    append_manual_adjustment(
        api, scape.consumer_id, scape.winery_id, 26.000,
        occurred_at="2026-07-15T00:00:00Z",
    )
    for _ in range(2):
        order = scape.create_order()
        screened = scape.screen(order["id"])
        exception = scape.raise_exception(
            screened["id"], screened["rejection_error_id"]
        )
        scape.decide_exception(exception["id"], "DENIED")
    return scape, scape.read_consumer()


def build_suspended_permit_order(api, landscape=None, lines=None):
    """A CLEARED, UNFULFILLED order frozen by permit revocation (PRD §3.2)."""
    scape = landscape or build_landscape(api)
    order = scape.create_order(lines=lines)
    scape.screen(order["id"])
    scape.revoke_permit()
    return scape, scape.read_order(order["id"])


def build_club_landscape(api, landscape=None, next_run_date="2026-08-20",
                         **subscription_overrides):
    """A landscape carrying one ACTIVE MONTHLY club subscription (PRD §3.8)."""
    scape = landscape or build_landscape(api)
    subscription = scape.create_subscription(
        next_run_date=next_run_date, **subscription_overrides
    )
    return scape, subscription


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api():
    """The API client under test."""
    return DtcApiClient()


@pytest.fixture
def clock(api):
    """The logical clock parked at its startup default (PRD §2.4)."""
    set_clock(api, CLOCK_STARTUP_DEFAULT)
    return CLOCK_STARTUP_DEFAULT


@pytest.fixture
def landscape(api):
    """The full pre-screening landscape."""
    return build_landscape(api)


@pytest.fixture
def bare_landscape(api):
    """Clock, winery and TX state rule only."""
    return build_bare_landscape(api)


@pytest.fixture
def landscape_pending_permit(api):
    """The landscape with its TX permit still PENDING."""
    return build_landscape(api, activate_permit_row=False)


@pytest.fixture
def landscape_unverified_consumer(api):
    """The landscape with consumer Ada's identity not yet verified."""
    return build_landscape(api, verify_consumer_id=False)


@pytest.fixture
def cleared_order(api, landscape):
    """A CLEARED, UNFULFILLED canonical order plus its landscape."""
    _, order = build_cleared_order(api, landscape)
    return landscape, order


@pytest.fixture
def labeled_order(api, landscape):
    _, order, shipment = build_labeled_order(api, landscape)
    return landscape, order, shipment


@pytest.fixture
def in_transit_order(api, landscape):
    _, order, shipment = build_in_transit_order(api, landscape)
    return landscape, order, shipment


@pytest.fixture
def delivered_order(api, landscape):
    _, order, shipment = build_delivered_order(api, landscape)
    return landscape, order, shipment


@pytest.fixture
def returned_order(api, landscape):
    _, order, shipment = build_returned_order(api, landscape)
    return landscape, order, shipment


@pytest.fixture
def override_pending_order(api, landscape):
    _, order = build_override_pending_order(api, landscape)
    return landscape, order


@pytest.fixture
def suspended_permit_order(api, landscape):
    _, order = build_suspended_permit_order(api, landscape)
    return landscape, order


@pytest.fixture
def club_landscape(api, landscape):
    _, subscription = build_club_landscape(api, landscape)
    return landscape, subscription
