"""Requests that trip two gates at once, and the gate that must win."""
from test_helpers import (
    ADMIN,
    DE_RULE_FULL,
    NY_RULE_FULL,
    OFFICER,
    ApiErrorId,
    accept_appointment,
    activate_registration,
    draft_standalone_filing,
    new_certificate,
    new_clearance,
    new_client,
    new_entity,
    new_home_registration,
    new_obligation,
    new_payment,
    ops_run,
    propose_appointment,
    publish_rule,
    read_filing,
    read_payment,
    read_registration,
    set_clock,
    validate_error,
    validate_paginated,
)

SHARE_FACTS = {
    "authorized_shares": 8000,
    "issued_shares": 4000,
    "total_gross_assets_cents": 12000000,
}


def _delinquent_home_with_a_stale_certificate():
    """A DE home registration driven DELINQUENT, holding a certificate that is also
    far too old for the New York freshness window."""
    publish_rule(DE_RULE_FULL)
    publish_rule(NY_RULE_FULL)
    client = new_client()
    entity = new_entity(client["id"], **SHARE_FACTS)
    registration = new_home_registration(entity["id"])
    appointment = propose_appointment(registration)
    accept_appointment(appointment["id"])
    activate_registration(registration["id"])
    certificate = new_certificate(registration["id"], issued_on="2026-06-01")
    clearance = new_clearance(entity["id"], result="AVAILABLE", state_code="NY")
    new_obligation(registration["id"], "ANNUAL_REPORT", 2027)
    set_clock("2027-04-15T00:00:00Z")
    ops_run()
    return {
        "client": client,
        "entity": entity,
        "registration": read_registration(registration["id"]),
        "certificate": certificate,
        "clearance": clearance,
    }


def _over_capture_against_another_clients_filing():
    """Client A holds a 5000-cent authorization; client B holds the only draft filing."""
    publish_rule(DE_RULE_FULL)
    client_a = new_client()
    client_b = new_client(legal_name="Beacon Holdings", billing_email="ap@beacon.example")
    entity_a = new_entity(client_a["id"])
    entity_b = new_entity(
        client_b["id"], legal_name="Southwind Widgets LLC", formation_date="2026-02-15"
    )
    new_home_registration(entity_a["id"])
    registration_b = new_home_registration(entity_b["id"])
    filing_b = draft_standalone_filing(
        registration_b["id"], "DISSOLUTION", expedite_tier="NONE"
    )
    payment_a = new_payment(client_a["id"], 5000)
    return {"payment_a": payment_a, "filing_b": filing_b}


def test_home_state_delinquency_is_reported_before_certificate_staleness(api):
    """PRD §2.9.1: "**Creating a foreign qualification** (`POST
    /legal-entities/{id}/foreign-qualifications`) evaluates, in this order: rung 18
    `ERR_NO_EFFECTIVE_STATE_RULE`, because a rule row must exist before anything can be
    priced; then rung 20 `ERR_DUPLICATE_REGISTRATION`, the interval-occupancy check;
    then rung 23 `ERR_HOME_STATE_DELINQUENT`, the sequencing gate that forbids
    qualifying outward out of a delinquent home state; then rung 24
    `ERR_CERTIFICATE_STALE`, the freshness of the good-standing certificate; and only
    last rung 25 `ERR_NAME_CONFLICT_UNRESOLVED`, name availability."
    PRD §2.9.1: "A request that would trip both rung 23 and rung 24 returns
    `ERR_HOME_STATE_DELINQUENT`."

    Design: Difficulty/priority_pair_validation_conflict/home_state_delinquency_outranks_stale_certificate
    """
    scene = _delinquent_home_with_a_stale_certificate()

    response = api.create_foreign_qualification(
        scene["entity"]["id"],
        {
            "state_code": "NY",
            "name_clearance_id": scene["clearance"]["id"],
            "good_standing_certificate_id": scene["certificate"]["id"],
        },
        OFFICER,
    )

    assert response.status_code == 409
    # The certificate is 318 days old against a 30-day window, so rung 24 would also
    # fail; the declared order makes rung 23 the reported error.
    validate_error(response, ApiErrorId.ERR_HOME_STATE_DELINQUENT.value)


def test_the_refused_qualification_leaves_the_portfolio_untouched(api):
    """PRD §3.2: "Home-state standing means this: the entity's `HOME` registration must
    not be in status `DELINQUENT`, `ADMIN_DISSOLVED` or `CLOSED_PERMANENT`. A firm that
    has fallen behind where it was formed may not expand into a new jurisdiction, and
    the attempt is rejected with `ERR_HOME_STATE_DELINQUENT`."
    PRD §3.11: "its `status` becomes `DELINQUENT`, its `delinquency_rank` is set to 3,
    its `version` increases by 1, and the entity's `compliance_posture` and then the
    client's `portfolio_delinquency_status` are recomputed."

    Design: Difficulty/priority_pair_validation_conflict/home_state_delinquency_outranks_stale_certificate
    """
    scene = _delinquent_home_with_a_stale_certificate()
    assert scene["registration"]["status"] == "DELINQUENT"

    api.create_foreign_qualification(
        scene["entity"]["id"],
        {
            "state_code": "NY",
            "name_clearance_id": scene["clearance"]["id"],
            "good_standing_certificate_id": scene["certificate"]["id"],
        },
        OFFICER,
    )

    assert read_registration(scene["registration"]["id"])["status"] == "DELINQUENT"
    _rows, meta = validate_paginated(
        api.list_registrations(ADMIN, params={"legal_entity_id": scene["entity"]["id"]})
    )
    assert meta["total_count"] == 1, "no New York registration row was created"


def test_over_capture_is_reported_before_the_ineligible_allocation_target(api):
    """PRD §2.9.1: "**Capturing a payment** (`POST /payments/{id}/capture`) evaluates, in
    this order: rung 16 `ERR_INVALID_STATE`, since the payment must be `AUTHORIZED`;
    then rung 35 `ERR_CAPTURE_EXCEEDS_AUTHORIZATION`; then rung 36
    `ERR_ALLOCATION_TARGET_INVALID`. A request that both over-captures and names an
    ineligible target returns `ERR_CAPTURE_EXCEEDS_AUTHORIZATION`."

    Design: Difficulty/priority_pair_validation_conflict/capture_over_authorization_outranks_invalid_allocation_target
    """
    scene = _over_capture_against_another_clients_filing()

    response = api.capture_payment(
        scene["payment_a"]["id"],
        {"capture_amount_cents": 6000, "target_filing_id": scene["filing_b"]["id"]},
        ADMIN,
    )

    assert response.status_code == 402
    validate_error(response, ApiErrorId.ERR_CAPTURE_EXCEEDS_AUTHORIZATION.value)


def test_the_refused_capture_moves_no_money_at_all(api):
    """PRD §3.8: "The payment is created in status `AUTHORIZED` with
    `captured_amount_cents`, `allocated_amount_cents`, `unallocated_amount_cents` and
    `refunded_amount_cents` all 0."
    PRD §3.8: "On success the payment moves `AUTHORIZED → CAPTURED`,
    `captured_amount_cents` is set to `capture_amount_cents`, the allocation waterfall
    runs, and the payment's `version` increases by 1."

    Design: Difficulty/priority_pair_validation_conflict/capture_over_authorization_outranks_invalid_allocation_target
    """
    scene = _over_capture_against_another_clients_filing()

    api.capture_payment(
        scene["payment_a"]["id"],
        {"capture_amount_cents": 6000, "target_filing_id": scene["filing_b"]["id"]},
        ADMIN,
    )

    payment = read_payment(scene["payment_a"]["id"])
    assert payment["status"] == "AUTHORIZED"
    assert payment["captured_amount_cents"] == 0
    assert read_filing(scene["filing_b"]["id"])["paid_amount_cents"] == 0
