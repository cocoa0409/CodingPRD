"""Payer coverage: authorisation, denial, appeal and the cash fallback."""

from test_helpers import (
    assert_lot_split,
    assert_prior_authorization,
    assert_same_instant,
    file_prior_authorization,
    make_pharmacy_operator_headers,
    make_provider_headers,
    platform_admin_headers,
    read_prescription,
    read_supply_lot,
    setup_active_prescription,
    setup_reserved_order,
    validate_error,
    validate_success,
    billing_admin_headers,
)

INSURED_MEMBER = {"payment_mode": "INSURANCE", "weight_kg": 95.0}
BRANDED_PHARMACY = {"name": "Brandline Rx", "dispense_type": "BRANDED"}


def test_denial_then_two_appeals_walk_the_payer_case_back_and_forth(api):
    """PRD §3.6: "**Appeal** is the member's second and third bite. A `Provider`
    appeals a denial, moving the authorisation `DENIED → APPEALED`; the request may
    carry a replacement `payer_reference`. The appeal increments `appeal_count` by
    one and clears both `decided_at` and `denial_reason`, putting the case back in
    front of the payer with no recorded decision."
    PRD §3.6: "The filing lands in `SUBMITTED` with `appeal_count` at zero,
    `decided_at` null, `denial_reason` null and `approved_through_at` null."

    Design: Difficulty/non_linear_state_machine/prior_authorization_denial_appeal_cycle_bounded_at_two
    """
    scenario = setup_active_prescription(
        patient={"email": "hana@example.com", "full_name": "Hana Vo", **INSURED_MEMBER}
    )
    provider_headers = make_provider_headers(scenario["clinician"]["id"])
    authorisation = file_prior_authorization(
        scenario["prescription"]["id"],
        scenario["clinician"]["id"],
        payer_reference="PA-88001",
    )
    assert_prior_authorization(authorisation)
    assert authorisation["status"] == "SUBMITTED"
    assert authorisation["appeal_count"] == 0

    denied = validate_success(
        api.decide_prior_authorization(
            authorisation["id"],
            {"decision": "DENIED", "denial_reason": "STEP_THERAPY_NOT_MET"},
            billing_admin_headers(),
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["appeal_count"] == 0

    appealed = validate_success(
        api.appeal_prior_authorization(
            authorisation["id"], {"payer_reference": "PA-88001-A1"}, provider_headers
        )
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1
    assert appealed["decided_at"] is None
    assert appealed["denial_reason"] is None

    validate_success(
        api.decide_prior_authorization(
            authorisation["id"],
            {"decision": "DENIED", "denial_reason": "STILL_NOT_MET"},
            billing_admin_headers(),
        )
    )
    second_appeal = validate_success(
        api.appeal_prior_authorization(
            authorisation["id"], {"payer_reference": "PA-88001-A2"}, provider_headers
        )
    )
    assert second_appeal["status"] == "APPEALED"
    assert second_appeal["appeal_count"] == 2


def test_third_appeal_is_refused_once_the_appeal_count_reaches_two(api):
    """PRD §3.6: "Appeals are capped: a prescription may be appealed at most twice,
    so an appeal filed when `appeal_count` has already reached 2 is rejected with
    `ERR_APPEAL_LIMIT_REACHED` (422). Note that the check is on the count *before*
    the increment — an appeal is admissible only while `appeal_count` is strictly
    less than 2."
    PRD §3.6: "Hop two flips the prescription's `active_route_mode` to `CASH` — the
    member is not abandoned, they are moved onto the self-pay fork, which changes
    both their pricing and the product form they will be routed to — and increments
    the prescription's `version` by one."

    Design: Difficulty/non_linear_state_machine/prior_authorization_denial_appeal_cycle_bounded_at_two
    """
    scenario = setup_active_prescription(
        patient={"email": "hana2@example.com", "full_name": "Hana Vo", **INSURED_MEMBER}
    )
    provider_headers = make_provider_headers(scenario["clinician"]["id"])
    authorisation = file_prior_authorization(
        scenario["prescription"]["id"],
        scenario["clinician"]["id"],
        payer_reference="PA-88001",
    )

    for reference, reason in (
        ("PA-88001-A1", "STEP_THERAPY_NOT_MET"),
        ("PA-88001-A2", "STILL_NOT_MET"),
    ):
        validate_success(
            api.decide_prior_authorization(
                authorisation["id"],
                {"decision": "DENIED", "denial_reason": reason},
                billing_admin_headers(),
            )
        )
        validate_success(
            api.appeal_prior_authorization(
                authorisation["id"], {"payer_reference": reference}, provider_headers
            )
        )

    validate_success(
        api.decide_prior_authorization(
            authorisation["id"],
            {"decision": "DENIED", "denial_reason": "FINAL"},
            billing_admin_headers(),
        )
    )

    refused = api.appeal_prior_authorization(
        authorisation["id"], {"payer_reference": "PA-88001-A3"}, provider_headers
    )
    validate_error(refused, "ERR_APPEAL_LIMIT_REACHED")

    final = validate_success(
        api.get_prior_authorization(authorisation["id"], platform_admin_headers())
    )
    assert final["status"] == "DENIED"
    assert final["appeal_count"] == 2

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["active_route_mode"] == "CASH"


def test_denial_flips_the_route_to_cash_and_cancels_the_branded_order(api):
    """PRD §3.6: "Hop three cancels every pharmacy order for that prescription
    whose `dispense_type_at_route` is `BRANDED` and whose status is `CREATED` or
    `RESERVED`, setting each one's `cancel_reason` to `PA_DENIED`; for the reserved
    ones this in turn returns their held units from the lot's `reserved_units` to
    its `available_units`."
    PRD §3.6: "Hop one sets `decided_at` to the clock and records the supplied
    `denial_reason`."

    Design: Difficulty/transitive_cascade/prior_auth_denial_three_hop_cascade_to_branded_order_release
    """
    scenario = setup_reserved_order(
        patient={"email": "lex@example.com", "full_name": "Lex Amara", **INSURED_MEMBER},
        pharmacy=BRANDED_PHARMACY,
        lot={"lot_code": "L-0003"},
    )
    authorisation = file_prior_authorization(
        scenario["prescription"]["id"],
        scenario["clinician"]["id"],
        payer_reference="PA-99001",
    )

    decided = validate_success(
        api.decide_prior_authorization(
            authorisation["id"],
            {"decision": "DENIED", "denial_reason": "NOT_MEDICALLY_NECESSARY"},
            billing_admin_headers(),
        )
    )

    assert decided["status"] == "DENIED"
    assert decided["denial_reason"] == "NOT_MEDICALLY_NECESSARY"

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["active_route_mode"] == "CASH"

    order = validate_success(
        api.get_pharmacy_order(scenario["order"]["id"], platform_admin_headers())
    )
    assert order["dispense_type_at_route"] == "BRANDED"
    assert order["status"] == "CANCELLED"
    assert order["cancel_reason"] == "PA_DENIED"


def test_denial_returns_the_held_units_to_the_lot(api):
    """PRD §2.10: "Reserving a pharmacy order moves `units_requested` from
    `available_units` to `reserved_units`; cancelling that order while it is
    reserved moves exactly the same quantity back from `reserved_units` to
    `available_units`, restoring both components to their pre-reservation values
    rather than merely restoring the sum."
    PRD §3.7: "Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`,
    increments the lot's `available_units` by `units_requested` and decrements its
    `reserved_units` by the same amount — restoring the pre-reservation split
    exactly, component for component — and additionally rewinds the prescription's
    `fulfillment_status` to `UNROUTED` when no other order for that prescription
    remains in `CREATED` or `RESERVED`."

    Design: Difficulty/transitive_cascade/prior_auth_denial_three_hop_cascade_to_branded_order_release
    """
    scenario = setup_reserved_order(
        patient={"email": "lex2@example.com", "full_name": "Lex Amara", **INSURED_MEMBER},
        pharmacy=BRANDED_PHARMACY,
        lot={"lot_code": "L-0003B", "total_units": 24},
    )
    held = read_supply_lot(scenario["lot"]["id"])
    assert_lot_split(held, available=22, reserved=2, dispensed=0)

    authorisation = file_prior_authorization(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    validate_success(
        api.decide_prior_authorization(
            authorisation["id"],
            {"decision": "DENIED", "denial_reason": "NOT_MEDICALLY_NECESSARY"},
            billing_admin_headers(),
        )
    )

    released = read_supply_lot(scenario["lot"]["id"])
    assert_lot_split(released, available=24, reserved=0, dispensed=0)

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["fulfillment_status"] == "UNROUTED"


def test_branded_shipment_without_an_approved_authorisation_is_refused(api):
    """PRD §3.7: "One coverage gate applies: when the order's
    `dispense_type_at_route` is `BRANDED` *and* the prescription's
    `active_route_mode` is `INSURANCE`, some prior authorisation for that
    prescription must be in `APPROVED` status with an `approved_through_at` at or
    after the clock. An expired approval fails this test just as a missing one
    does, and either is rejected with `ERR_PRIOR_AUTH_REQUIRED` (409)."

    Design: Difficulty/cross_entity_state_dependency/branded_shipment_requires_approved_prior_authorization
    """
    scenario = setup_reserved_order(
        patient={"email": "xan@example.com", "full_name": "Xan Poole", **INSURED_MEMBER},
        pharmacy=BRANDED_PHARMACY,
        lot={"lot_code": "L-0006"},
    )
    file_prior_authorization(
        scenario["prescription"]["id"],
        scenario["clinician"]["id"],
        payer_reference="PA-70002",
    )

    refused = api.ship_pharmacy_order(
        scenario["order"]["id"],
        {},
        make_pharmacy_operator_headers(scenario["pharmacy"]["id"]),
    )
    validate_error(refused, "ERR_PRIOR_AUTH_REQUIRED")

    still_reserved = validate_success(
        api.get_pharmacy_order(scenario["order"]["id"], platform_admin_headers())
    )
    assert still_reserved["status"] == "RESERVED"


def test_branded_shipment_succeeds_once_the_payer_approves(api):
    """PRD §3.6: "It sets `decided_at` to the clock and `approved_through_at` to
    the clock plus 180 days — roughly a six-month coverage horizon, after which the
    approval is stale for shipping purposes even though the status still reads
    `APPROVED`."
    PRD §3.7: "A successful shipment sets `shipped_at` to the clock, decrements the
    lot's `reserved_units` by `units_requested` and increments its
    `dispensed_units` by the same amount, and advances the prescription's fulfilment
    axis to `DISPENSED`."

    Design: Difficulty/cross_entity_state_dependency/branded_shipment_requires_approved_prior_authorization
    """
    scenario = setup_reserved_order(
        patient={"email": "xan2@example.com", "full_name": "Xan Poole", **INSURED_MEMBER},
        pharmacy=BRANDED_PHARMACY,
        lot={"lot_code": "L-0006B", "total_units": 24},
    )
    authorisation = file_prior_authorization(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )

    approved = validate_success(
        api.decide_prior_authorization(
            authorisation["id"], {"decision": "APPROVED"}, billing_admin_headers()
        )
    )
    assert approved["status"] == "APPROVED"
    assert_same_instant(
        approved["approved_through_at"], "2026-11-28T00:00:00Z", "approved_through_at"
    )

    shipped = validate_success(
        api.ship_pharmacy_order(
            scenario["order"]["id"],
            {},
            make_pharmacy_operator_headers(scenario["pharmacy"]["id"]),
        )
    )
    assert shipped["status"] == "SHIPPED"

    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=22, reserved=0, dispensed=2
    )
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["fulfillment_status"] == "DISPENSED"
