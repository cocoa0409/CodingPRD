"""Role model: exclusive operations, the shared clock, peer isolation and the two-man rule."""
from test_helpers import (
    api_client,
    calculate_run,
    commission_receipt_payload,
    compliance,
    controller,
    create_advisor_payload,
    credential_decision_payload,
    file_credential,
    make_advisor_headers,
    make_supplier_portal_headers,
    new_advisor,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    open_run,
    ops,
    read_advisor,
    read_booking,
    read_credential,
    read_run,
    read_supplier,
    seller_of_travel_credential_payload,
    setup_active_advisor,
    sign_agreement,
    suspend_advisor_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}
CABO_RAIL = {
    "name": "Cabo Rail",
    "accreditation_scheme": "IATA",
    "base_commission_pct": 0.08,
    "preferred_override_commission_pct": 0.11,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 45,
}


def _standard_schedule():
    return new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )


def test_no_role_may_reach_another_roles_exclusive_operation():
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles
    authorized for the target endpoint in the Section 4 table, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_each_role_is_denied_the_other_roles_exclusive_operations
    """
    schedule = _standard_schedule()
    supplier = new_supplier(**MERIDIAN)
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    sign_agreement(advisor["id"], schedule["id"], effective_date="2026-01-01")
    credential = file_credential(
        advisor["id"],
        seller_of_travel_credential_payload(
            jurisdiction_state_code="NY",
            credential_number="NY-SOT-40118",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
        ),
    )
    run = open_run("2026-08")

    validate_error(
        api_client.calculate_settlement_run(run["id"], ops()),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.activate_advisor(advisor["id"], controller("ctrl-1")),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_advisor(
            create_advisor_payload(
                legal_name="Sam Ortiz",
                email="sam.ortiz@example.com",
                seller_of_travel_state="NY",
            ),
            compliance(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.decide_compliance_credential(
            credential["id"],
            credential_decision_payload("VERIFY"),
            make_advisor_headers(advisor["id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.suspend_advisor(
            advisor["id"],
            suspend_advisor_payload("Supplier-initiated suspension"),
            make_supplier_portal_headers(supplier["id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    untouched_run = read_run(run["id"])
    assert untouched_run["status"] == "OPEN"
    assert untouched_run["calculated_by_user_id"] is None

    assert read_advisor(advisor["id"])["status"] == "DRAFT"
    _, meta = validate_paginated(api_client.list_advisors(ops()))
    assert meta["total_count"] == 1

    undecided = read_credential(credential["id"])
    assert undecided["status"] == "PENDING_REVIEW"
    assert undecided["verified_by_user_id"] is None


def test_only_the_three_operator_roles_may_move_the_clock():
    """PRD §4 authorizes `POST /host-agency/_clock/set_current_utc` for `HostOperations`,
    `HostController` and `ComplianceOfficer` alone, and PRD §2.1 says that when "the declared
    role is not among the roles authorized for the target endpoint in the Section 4 table, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.5: "the response reports how much moved: `current_utc` echoes the new clock,
    `expired_credential_count` reports how many verified credentials lapsed as a result, and
    `refreshed_claim_count` reports how many open commission claims had their aging
    recomputed."

    Design: Corner/rbac/corner_clock_is_shared_by_the_three_opaque_roles_only
    """
    supplier = new_supplier(**MERIDIAN)
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )

    by_ops = validate_success(api_client.advance_clock_to("2026-08-02T00:00:00Z", ops()))
    assert by_ops["current_utc"].startswith("2026-08-02T00:00:00")
    assert by_ops["expired_credential_count"] == 0
    assert by_ops["refreshed_claim_count"] == 0

    by_controller = validate_success(
        api_client.advance_clock_to("2026-08-03T00:00:00Z", controller("ctrl-1"))
    )
    assert by_controller["current_utc"].startswith("2026-08-03T00:00:00")

    by_compliance = validate_success(
        api_client.advance_clock_to("2026-08-04T00:00:00Z", compliance())
    )
    assert by_compliance["current_utc"].startswith("2026-08-04T00:00:00")
    assert by_compliance["expired_credential_count"] == 0
    assert by_compliance["refreshed_claim_count"] == 0

    validate_error(
        api_client.advance_clock_to(
            "2026-09-01T00:00:00Z", make_advisor_headers(advisor["id"])
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.advance_clock_to(
            "2026-09-01T00:00:00Z", make_supplier_portal_headers(supplier["id"])
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    still_there = validate_success(
        api_client.advance_clock_to("2026-08-04T00:00:00Z", ops())
    )
    assert still_there["current_utc"].startswith("2026-08-04T00:00:00")

    as_advisor = validate_success(
        api_client.get_advisor(advisor["id"], make_advisor_headers(advisor["id"]))
    )
    as_supplier = validate_success(
        api_client.get_advisor(
            advisor["id"], make_supplier_portal_headers(supplier["id"])
        )
    )
    assert as_advisor["id"] == advisor["id"]
    assert as_supplier["id"] == advisor["id"]


def test_one_supplier_cannot_act_on_a_peers_booking():
    """PRD §3.6: "the acting supplier's `X-User-ID` must equal the booking's `supplier_id`,
    or the request is refused with `ERR_OWNERSHIP_VIOLATION`"

    Design: Corner/rbac/corner_supplier_portal_cannot_reach_another_suppliers_booking
    """
    owner = new_supplier(**MERIDIAN)
    peer = new_supplier(**CABO_RAIL)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=_standard_schedule(),
        suppliers=[owner, peer],
    )
    advisor = ctx["advisor"]
    client = new_client(advisor["id"], full_name="Nadia Okoye", home_state_code="NY")
    booking = new_booking(
        advisor["id"],
        owner["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )

    validate_error(
        api_client.confirm_booking(
            booking["id"], make_supplier_portal_headers(peer["id"])
        ),
        "ERR_OWNERSHIP_VIOLATION",
        403,
    )

    peer_read = validate_success(
        api_client.get_booking(
            booking["id"], make_supplier_portal_headers(peer["id"])
        )
    )
    assert peer_read["booking_status"] == "SUBMITTED"

    confirmed = validate_success(
        api_client.confirm_booking(
            booking["id"], make_supplier_portal_headers(owner["id"])
        )
    )
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["commission_status"] == "EXPECTED"

    validate_error(
        api_client.record_commission_receipt(
            booking["id"],
            commission_receipt_payload(100_000, "2026-08-01"),
            make_supplier_portal_headers(peer["id"]),
        ),
        "ERR_OWNERSHIP_VIOLATION",
        403,
    )
    assert read_booking(booking["id"])["received_commission_cents"] == 0

    assert read_supplier(peer["id"])["total_outstanding_cents"] == 0
    assert read_supplier(owner["id"])["total_outstanding_cents"] == 0


def test_the_two_user_control_binds_even_when_no_money_moves():
    """PRD §2.11: "Within `HostController`, the control tightens further: the `X-User-ID`
    that calculated a run may not be the `X-User-ID` that posts it."

    Design: Corner/rbac/corner_segregation_of_duties_holds_even_for_an_empty_run
    """
    run = open_run("2026-08")
    calculated = calculate_run(run["id"], "ctrl-1")
    assert calculated["status"] == "CALCULATED"
    assert calculated["calculated_by_user_id"] == "ctrl-1"
    assert calculated["statement_count"] == 0

    validate_error(
        api_client.post_settlement_run(run["id"], controller("ctrl-1")),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )
    refused = read_run(run["id"])
    assert refused["status"] == "CALCULATED"
    assert refused["posted_by_user_id"] is None

    posted = validate_success(
        api_client.post_settlement_run(run["id"], controller("ctrl-2"))
    )
    assert posted["posted_by_user_id"] == "ctrl-2"
    assert posted["status"] == "CLOSED"
