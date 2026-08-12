"""Strict boundaries: certificate age, and the volume-discount threshold."""
from test_helpers import (
    ADMIN,
    DE_RULE_FULL,
    NY_RULE_FULL,
    OFFICER,
    TX_RULE_FULL,
    ApiErrorId,
    accept_appointment,
    activate_registration,
    new_certificate,
    new_clearance,
    new_client,
    new_entity,
    new_home_registration,
    new_obligation,
    propose_appointment,
    publish_rule,
    read_client,
    set_clock,
    setup_active_home_registration,
    validate_error,
    validate_paginated,
    validate_success,
)

SHARE_FACTS = {
    "authorized_shares": 8000,
    "issued_shares": 4000,
    "total_gross_assets_cents": 12000000,
}


def _certificate_age_scene():
    """A DE home registration in good standing, one certificate issued 2026-06-01, and
    two cleared names — one for Texas, one for New York."""
    publish_rule(DE_RULE_FULL)
    publish_rule(TX_RULE_FULL)
    publish_rule(NY_RULE_FULL)
    client = new_client()
    entity = new_entity(client["id"])
    registration = new_home_registration(entity["id"])
    appointment = propose_appointment(registration)
    accept_appointment(appointment["id"])
    activate_registration(registration["id"])
    return {
        "client": client,
        "entity": entity,
        "registration": registration,
        "certificate": new_certificate(registration["id"], issued_on="2026-06-01"),
        "clearance_tx": new_clearance(entity["id"], result="AVAILABLE", state_code="TX"),
        "clearance_ny": new_clearance(entity["id"], result="AVAILABLE", state_code="NY"),
    }


def _four_open_obligations_scene():
    """An ACTIVE Delaware registration carrying exactly four open obligations."""
    scene = setup_active_home_registration(
        DE_RULE_FULL, entity_overrides=dict(SHARE_FACTS)
    )
    registration_id = scene["registration"]["id"]
    new_obligation(registration_id, "ANNUAL_REPORT", 2027)
    new_obligation(registration_id, "FRANCHISE_TAX", 2027)
    new_obligation(registration_id, "ANNUAL_REPORT", 2028)
    new_obligation(registration_id, "FRANCHISE_TAX", 2028)
    return scene


def test_a_certificate_one_day_inside_the_window_still_qualifies(api):
    """PRD §3.2: "The server takes the rule effective for the target `state_code` on the
    current clock date, computes the certificate's age in days as the current clock date
    minus its `issued_on`, and accepts the certificate only when that age is strictly
    less than the target rule's `good_standing_freshness_days`."
    PRD §3.2: "with the default freshness of 30 days, an age of 29 days is the oldest
    certificate accepted."
    PRD §3.2: "On success the server creates a registration in `PENDING` with
    `registration_kind` `FOREIGN`, `state_code` set to the requested target, and
    `name_clearance_id` set to the referenced clearance."

    Design: Difficulty/boundary_precision_check/certificate_age_exactly_equal_to_freshness_days_is_stale
    """
    scene = _certificate_age_scene()

    # 2026-06-01 to 2026-06-30 is 29 days, one day inside the strict 30-day window.
    set_clock("2026-06-30T00:00:00Z")
    data = validate_success(
        api.create_foreign_qualification(
            scene["entity"]["id"],
            {
                "state_code": "TX",
                "name_clearance_id": scene["clearance_tx"]["id"],
                "good_standing_certificate_id": scene["certificate"]["id"],
            },
            OFFICER,
        ),
        201,
    )

    assert data["state_code"] == "TX"
    assert data["registration_kind"] == "FOREIGN"
    assert data["status"] == "PENDING"


def test_a_certificate_exactly_at_the_window_is_already_stale(api):
    """PRD §3.2: "An age exactly equal to `good_standing_freshness_days` is stale and is
    rejected with `ERR_CERTIFICATE_STALE`; with the default freshness of 30 days, an
    age of 29 days is the oldest certificate accepted."
    PRD §3.2: ""Within N days" in this system always means strictly fewer than N."

    Design: Difficulty/boundary_precision_check/certificate_age_exactly_equal_to_freshness_days_is_stale
    """
    scene = _certificate_age_scene()
    set_clock("2026-06-30T00:00:00Z")
    validate_success(
        api.create_foreign_qualification(
            scene["entity"]["id"],
            {
                "state_code": "TX",
                "name_clearance_id": scene["clearance_tx"]["id"],
                "good_standing_certificate_id": scene["certificate"]["id"],
            },
            OFFICER,
        ),
        201,
    )

    # 2026-06-01 to 2026-07-01 is exactly 30 days, which is no longer strictly inside.
    set_clock("2026-07-01T00:00:00Z")
    response = api.create_foreign_qualification(
        scene["entity"]["id"],
        {
            "state_code": "NY",
            "name_clearance_id": scene["clearance_ny"]["id"],
            "good_standing_certificate_id": scene["certificate"]["id"],
        },
        OFFICER,
    )

    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_CERTIFICATE_STALE.value)

    _rows, meta = validate_paginated(
        api.list_registrations(ADMIN, params={"legal_entity_id": scene["entity"]["id"]})
    )
    assert meta["total_count"] == 2, "the Delaware home row and the Texas row, no more"


def test_four_prior_open_obligations_still_pay_the_undiscounted_service_fee(api):
    """PRD §3.5: "The comparison is inclusive on the threshold: a prior open count of 4
    gets no discount and pays 4900, while a prior open count of 5 gets the discount and
    pays 4165."
    PRD §3.5: "`service_fee_cents` is the platform's own charge and is **evaluated
    exactly once, at creation, and never recomputed** by any later ops-run, filing or
    rebuild. The base charge is 4900 cents."

    Design: Difficulty/boundary_precision_check/volume_discount_threshold_boundary_four_versus_five_prior_open
    """
    scene = _four_open_obligations_scene()

    fifth = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2029)
    sixth = new_obligation(scene["registration"]["id"], "FRANCHISE_TAX", 2029)

    assert fifth["service_fee_cents"] == 4900
    assert sixth["service_fee_cents"] == 4165


def test_the_threshold_moves_the_total_and_the_open_count_by_exactly_one_row(api):
    """PRD §3.5: "The discount itself is 4900 multiplied by 1500 and divided by 10000,
    rounded half up, which is exactly 735 cents, so the discounted service fee is
    exactly 4165 cents and the undiscounted fee is 4900 cents."
    PRD §2.11: "`portfolio_open_obligation_count` is the number of obligations in one of
    the four open statuses across every registration of every legal entity of the
    client; `portfolio_outstanding_cents` is the sum of `total_due_cents` over exactly
    those same rows; and `portfolio_entity_count` is the number of the client's legal
    entities whose `lifecycle_status` is anything other than `DISSOLVED`."

    Design: Difficulty/boundary_precision_check/volume_discount_threshold_boundary_four_versus_five_prior_open
    """
    scene = _four_open_obligations_scene()

    fifth = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2029)
    sixth = new_obligation(scene["registration"]["id"], "FRANCHISE_TAX", 2029)

    # 5000 annual-report fee + 0 tax + 0 late + 4900 service = 9900.
    assert fifth["total_due_cents"] == 9900
    # 5000 franchise-tax filing fee + 25000 tier tax + 0 late + 4165 service = 34165.
    assert sixth["total_due_cents"] == 34165

    assert read_client(scene["client"]["id"])["portfolio_open_obligation_count"] == 6
