"""Cross-entity state preconditions of the Winery DTC Shipping Compliance API.

Two dependencies where a write or an assessment against one entity is decided by
the *status* of a different entity, and where the depended-on row is moved
between the arms while the dependent row's own body never changes:

* order screening against the destination `StatePermit`'s `status`
  (`PENDING` versus `ACTIVE`), and
* label production against the `CarrierEnrollment`'s `status`, cycled
  `APPROVED` -> `SUSPENDED` -> `APPROVED` under an unchanging `CLEARED` order.

Every expectation below is quoted from PRD.md and nothing else.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (client under test)
from test_helpers.assertions import (
    assert_cents,
    assert_charge_chain,
    assert_ledger_entry,
    assert_liters,
    assert_order_dimensions,
    assert_rejection,
    assert_tracking_number,
)
from test_helpers.constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_TOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
)
from test_helpers.fixtures import (
    activate_permit,
    build_landscape,
    decide_enrollment,
)
from test_helpers.test_users import OFFICER_A


# ---------------------------------------------------------------------------
# Instance 1: order clearance depends on the destination permit being ACTIVE
# ---------------------------------------------------------------------------
def _screen_while_permit_is_pending(api):
    """Screen the canonical TX order while the TX permit is still `PENDING`.

    The carrier enrollment is `APPROVED` and consumer Ada is ID-verified, and the
    canonical 4.500 L order sits far inside the 27.000 L TX per-consumer limit, so
    the permit's `status` is the only failing rung of the ladder.
    """
    scape = build_landscape(api, activate_permit_row=False)
    order_a = scape.create_order()
    return scape, scape.screen(order_a["id"])


def test_screening_rejects_the_order_while_the_destination_permit_is_pending(api):
    """A `PENDING` permit authorizes nothing, so the screen records the failure.

    "A filed permit opens in `PENDING`, and a `PENDING` permit authorizes
    nothing." (PRD 3.2)

    "A permit in `PENDING`, `RENEWAL_FILED` or `REVOKED` authorizes no clearance
    and records `ERR_PERMIT_NOT_ACTIVE`." (PRD 3.6)

    "If the highest-ranked failing check is not one of the three overridable ones,
    the order is rejected and — since `REJECTED` is terminal on the compliance
    axis — the order is finished." (PRD 3.6)

    Design: Difficulty/cross_entity_state_dependency/order_clearance_requires_the_destination_permit_to_be_active
    """
    scape, order_a = _screen_while_permit_is_pending(api)

    assert scape.read_permit()["status"] == "PENDING"
    assert_order_dimensions(
        order_a, compliance_status="REJECTED", fulfillment_status="UNFULFILLED"
    )
    assert_rejection(order_a, "ERR_PERMIT_NOT_ACTIVE")


def test_rejected_order_moves_neither_the_ledger_nor_the_winery_accrual(api):
    """A rejection appends no ledger entry and leaves the accrual alone.

    "A **`DRAFT` → `REJECTED`** outcome writes the failing identifier into
    `rejection_error_id` and does nothing else: no ledger entry is appended, and
    `Winery.excise_accrued_cents` is untouched." (PRD 3.6)

    Design: Difficulty/cross_entity_state_dependency/order_clearance_requires_the_destination_permit_to_be_active
    """
    scape, order_a = _screen_while_permit_is_pending(api)

    assert_rejection(order_a, "ERR_PERMIT_NOT_ACTIVE")
    assert scape.ledger_rows(consumer_id=scape.consumer_id) == []
    assert_cents(
        scape.read_winery()["excise_accrued_cents"], 0, "excise_accrued_cents"
    )
    # The money frozen at creation survives the rejection untouched (PRD 3.5).
    assert_charge_chain(
        order_a,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        total_cents=CANONICAL_ORDER_TOTAL_CENTS,
    )


def test_activating_the_destination_permit_clears_an_identical_order(api):
    """Activation flips the dependency and the very same order body clears.

    "A `ComplianceOfficer` activates it — a `PENDING` → `ACTIVE` move — and that is
    only permitted once the permit's `effective_date` has arrived, meaning
    `effective_date` falls on or before the logical clock date." (PRD 3.2)

    "It stamps `cleared_at` from the logical clock and clears `rejection_error_id`
    back to null." (PRD 3.6)

    "The order's `adult_signature_required` flag is taken from the governing state
    rule's `adult_signature_required` at creation and re-asserted from the same
    state rule when the order's compliance dimension first reaches `CLEARED`;
    because the source is the same row in both cases, the recorded value is the
    state's requirement either way." (PRD 3.5)

    Design: Difficulty/cross_entity_state_dependency/order_clearance_requires_the_destination_permit_to_be_active
    """
    scape, order_a = _screen_while_permit_is_pending(api)

    activated = activate_permit(api, scape.permit_id)
    assert activated["status"] == "ACTIVE"

    order_b = scape.screen(scape.create_order()["id"])

    assert_order_dimensions(
        order_b, compliance_status="CLEARED", fulfillment_status="UNFULFILLED"
    )
    assert order_b["rejection_error_id"] is None
    assert order_b["adult_signature_required"] is True
    # Nothing about the order itself differs between the two arms.
    assert_charge_chain(order_b, total_cents=CANONICAL_ORDER_TOTAL_CENTS)
    assert order_b["total_cents"] == order_a["total_cents"]


def test_only_the_cleared_order_moves_the_ledger_and_the_winery_accrual(api):
    """The clearance debit and the excise accrual belong to order B alone.

    "It appends a volume-ledger entry with `event_type` `SHIPMENT_ACCEPTED`,
    `liters` equal to positive `total_liters`, `occurred_at` at the logical clock,
    `order_id` pointing at the order, `shipment_id` null, and `state_code` equal to
    the order's `ship_to_state_code`." (PRD 3.6)

    "The winery's `excise_accrued_cents` grows by the order's `excise_tax_cents` —
    that counter is the running sum of `excise_tax_cents` across every order of the
    winery that has reached `CLEARED` at least once — and `Winery.version`
    increments by 1." (PRD 3.6)

    Design: Difficulty/cross_entity_state_dependency/order_clearance_requires_the_destination_permit_to_be_active
    """
    scape, order_a = _screen_while_permit_is_pending(api)
    activate_permit(api, scape.permit_id)
    order_b = scape.screen(scape.create_order()["id"])

    rows = scape.ledger_rows(consumer_id=scape.consumer_id)
    assert len(rows) == 1, f"Expected exactly one ledger row, got {rows}"
    assert_ledger_entry(
        rows[0],
        event_type="SHIPMENT_ACCEPTED",
        liters=CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order_b["id"],
    )
    assert rows[0]["shipment_id"] is None
    assert rows[0]["order_id"] != order_a["id"]
    assert_liters(
        scape.read_consumer()["rolling_liters_by_state"]["TX"],
        CANONICAL_ORDER_TOTAL_LITERS,
        "rolling_liters_by_state[TX]",
    )
    assert_cents(
        scape.read_winery()["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )


def test_activating_the_permit_does_not_rescue_the_rejected_order(api):
    """`REJECTED` is terminal, so the upstream fix cannot be replayed onto it.

    "An order already sitting at `CLEARED`, `REJECTED` or `OVERRIDE_PENDING` cannot
    be screened again, and the attempt is refused with `ERR_ORDER_ALREADY_SCREENED`
    (HTTP 409)." (PRD 3.6)

    Design: Difficulty/cross_entity_state_dependency/order_clearance_requires_the_destination_permit_to_be_active
    """
    scape, order_a = _screen_while_permit_is_pending(api)
    activate_permit(api, scape.permit_id)

    validate_error(
        api.screen_order(order_a["id"], {}, OFFICER_A),
        "ERR_ORDER_ALREADY_SCREENED",
        409,
    )

    still_rejected = scape.read_order(order_a["id"])
    assert_order_dimensions(still_rejected, compliance_status="REJECTED")
    assert_rejection(still_rejected, "ERR_PERMIT_NOT_ACTIVE")


# ---------------------------------------------------------------------------
# Instance 2: label creation depends on the enrollment being APPROVED
# ---------------------------------------------------------------------------
def _suspend_enrollment_under_two_cleared_orders(api):
    """Label order A while the enrollment is `APPROVED`, then suspend it.

    Order A is `CLEARED` and already carries a `LABEL_CREATED` shipment; order B is
    `CLEARED` and still `UNFULFILLED`.  Together the two orders put 9.000 L against
    the consumer's 27.000 L TX limit, so no volume rung can fire.  The carrier then
    posts a `SUSPENDED` decision on the single enrollment both orders point at.
    """
    scape = build_landscape(api)
    order_a = scape.screen(scape.create_order()["id"])
    shipment_a = scape.label(order_a["id"])
    order_b = scape.screen(scape.create_order()["id"])
    suspended = decide_enrollment(api, scape.enrollment_id, "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"
    return scape, order_a, shipment_a, order_b


def test_label_is_refused_while_the_enrollment_sits_in_suspended(api):
    """The shipment write reads the enrollment's status and raises a real error.

    "While an enrollment sits in `SUSPENDED`, no new label may be drawn against it;
    the attempt is refused with `ERR_CARRIER_NOT_ENROLLED`." (PRD 3.3)

    "The named enrollment must be in `APPROVED` status and must belong to the
    order's own winery, and the enrolled program's `states_served` must contain the
    order's `ship_to_state_code`; a suspended or foreign enrollment, or a program
    that does not serve the destination, is refused with
    `ERR_CARRIER_NOT_ENROLLED`." (PRD 3.7)

    Design: Difficulty/cross_entity_state_dependency/label_creation_requires_an_approved_enrollment_and_survives_the_suspend_reapprove_cycle
    """
    scape, _order_a, _shipment_a, order_b = _suspend_enrollment_under_two_cleared_orders(
        api
    )

    validate_error(
        api.create_shipment(
            f.shipment_payload(order_b["id"], scape.enrollment_id), scape.operator
        ),
        "ERR_CARRIER_NOT_ENROLLED",
        422,
    )

    frozen = scape.read_order(order_b["id"])
    assert_order_dimensions(
        frozen, compliance_status="CLEARED", fulfillment_status="UNFULFILLED"
    )
    rows, meta = validate_paginated(
        api.list_shipments(scape.officer, {"order_id": order_b["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, (
        f"The refused label must persist nothing, got {rows}"
    )


def test_reapproving_the_enrollment_lets_the_same_label_request_succeed(api):
    """`SUSPENDED` -> `APPROVED` re-satisfies the dependency and the label lands.

    "Approval is reachable from both `PENDING` and `SUSPENDED` — a `PENDING` →
    `APPROVED` first approval and a `SUSPENDED` → `APPROVED` reinstatement are both
    legitimate, and the reinstatement path is what closes the `APPROVED` →
    `SUSPENDED` → `APPROVED` cycle on a single enrollment row." (PRD 3.3)

    "A successful label creates a shipment in `status` `LABEL_CREATED` with a
    server-minted `tracking_number` formatted as `TRK-` followed by eight
    hexadecimal characters." (PRD 3.7)

    "The shipment's own `adult_signature_required` is copied from the order's
    `adult_signature_required`, and its `adult_signature_service_code` is copied
    from the enrolled program's `adult_signature_service_code` when a signature is
    required and is null when it is not." (PRD 3.7)

    Design: Difficulty/cross_entity_state_dependency/label_creation_requires_an_approved_enrollment_and_survives_the_suspend_reapprove_cycle
    """
    scape, _order_a, _shipment_a, order_b = _suspend_enrollment_under_two_cleared_orders(
        api
    )
    validate_error(
        api.create_shipment(
            f.shipment_payload(order_b["id"], scape.enrollment_id), scape.operator
        ),
        "ERR_CARRIER_NOT_ENROLLED",
        422,
    )

    reinstated = decide_enrollment(api, scape.enrollment_id, "APPROVED")
    assert reinstated["status"] == "APPROVED"

    shipment_b = scape.label(order_b["id"])

    assert shipment_b["status"] == "LABEL_CREATED"
    assert shipment_b["order_id"] == order_b["id"]
    assert_tracking_number(shipment_b["tracking_number"])
    assert shipment_b["adult_signature_required"] is True
    assert shipment_b["adult_signature_service_code"] == "AS21"
    assert shipment_b["reroute_count"] == 0


def test_the_order_dimensions_survive_the_suspend_reapprove_cycle(api):
    """The dependent order never moved while the depended-on row cycled.

    "The order moves `UNFULFILLED` → `LABELED`." (PRD 3.7)

    "Neither dimension restricts the other's reachable values except where a rule in
    §3 says so in as many words." (PRD 2.11)

    Design: Difficulty/cross_entity_state_dependency/label_creation_requires_an_approved_enrollment_and_survives_the_suspend_reapprove_cycle
    """
    scape, _order_a, _shipment_a, order_b = _suspend_enrollment_under_two_cleared_orders(
        api
    )
    validate_error(
        api.create_shipment(
            f.shipment_payload(order_b["id"], scape.enrollment_id), scape.operator
        ),
        "ERR_CARRIER_NOT_ENROLLED",
        422,
    )
    decide_enrollment(api, scape.enrollment_id, "APPROVED")
    scape.label(order_b["id"])

    labelled = scape.read_order(order_b["id"])
    assert_order_dimensions(
        labelled, compliance_status="CLEARED", fulfillment_status="LABELED"
    )
    assert labelled["rejection_error_id"] is None


def test_suspension_does_not_retract_a_label_already_issued(api):
    """The dependency is evaluated at write time only.

    "Producing the carrier label is reserved to the `WineryOperator` and is the
    moment at which the compliance decision becomes irreversible." (PRD 3.7)

    "Shipments may be listed filtered by `order_id`, `carrier_enrollment_id`,
    `status` and by `replacement_of_shipment_id`, that last filter being the way to
    find the replacement drawn for a particular returned package." (PRD 3.7)

    Design: Difficulty/cross_entity_state_dependency/label_creation_requires_an_approved_enrollment_and_survives_the_suspend_reapprove_cycle
    """
    scape, order_a, shipment_a, order_b = _suspend_enrollment_under_two_cleared_orders(
        api
    )

    # The pre-existing label is untouched while the enrollment is SUSPENDED.
    assert scape.read_shipment(shipment_a["id"])["status"] == "LABEL_CREATED"
    assert_order_dimensions(
        scape.read_order(order_a["id"]),
        compliance_status="CLEARED",
        fulfillment_status="LABELED",
    )

    decide_enrollment(api, scape.enrollment_id, "APPROVED")
    scape.label(order_b["id"])

    assert scape.read_shipment(shipment_a["id"])["status"] == "LABEL_CREATED"
    _rows, meta = validate_paginated(
        api.list_shipments(
            scape.officer, {"carrier_enrollment_id": scape.enrollment_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected two shipments against the enrollment, got {meta['total_count']}"
    )
