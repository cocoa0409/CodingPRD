"""State machines: initial states, undeclared triggers, terminal lockdown, closure."""
from test_helpers import (
    api_client,
    calculate_run,
    compliance,
    confirm_booking,
    controller,
    create_booking_payload,
    credential_decision_payload,
    decide_credential,
    eo_policy_credential_payload,
    file_credential,
    make_advisor_headers,
    new_advisor,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    open_run,
    ops,
    pay_statement,
    read_advisor,
    read_booking,
    read_credential,
    read_run,
    record_receipt,
    seller_of_travel_credential_payload,
    set_clock,
    setup_active_advisor,
    sign_agreement,
    statements_for_run,
    training_cert_credential_payload,
    validate_error,
    validate_success,
)

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def test_every_freshly_created_row_starts_in_its_declared_initial_state():
    """PRD §3.8: "A new run begins in `OPEN` with `statement_count` and all seven monetary
    totals at 0 and both `calculated_by_user_id` and `posted_by_user_id` null."

    Design: Corner/state_machines/corner_initial_states_of_every_freshly_created_row
    """
    schedule = new_split_schedule()
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    assert advisor["status"] == "DRAFT"

    agreement = sign_agreement(advisor["id"], schedule["id"], effective_date="2026-01-01")
    assert agreement["status"] == "ACTIVE"

    credential = file_credential(
        advisor["id"],
        training_cert_credential_payload(
            credential_number="TRN-2026-A",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
        ),
    )
    assert credential["status"] == "PENDING_REVIEW"
    assert credential["verified_at"] is None
    assert credential["verified_by_user_id"] is None

    run = open_run("2026-06")
    assert run["status"] == "OPEN"
    assert run["statement_count"] == 0
    assert run["gross_commission_cents"] == 0
    assert run["advisor_share_total_cents"] == 0
    assert run["chargeback_total_cents"] == 0
    assert run["platform_fee_total_cents"] == 0
    assert run["marketing_fund_total_cents"] == 0
    assert run["net_payout_total_cents"] == 0
    assert run["calculated_by_user_id"] is None
    assert run["posted_by_user_id"] is None


def test_a_trigger_absent_from_the_current_state_changes_nothing():
    """PRD §3.2: "Suspending an advisor who is not `ACTIVE`, or reinstating one who is not
    `SUSPENDED`, is reported as `ERR_INVALID_ADVISOR_STATE`."

    Design: Corner/state_machines/corner_triggers_absent_from_the_current_state_are_rejected
    """
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    run = open_run("2026-06")

    validate_error(
        api_client.suspend_advisor(
            advisor["id"],
            {"reason": "Attempted suspension of a DRAFT advisor"},
            compliance(),
        ),
        "ERR_INVALID_ADVISOR_STATE",
        409,
    )
    validate_error(
        api_client.reinstate_advisor(advisor["id"], compliance()),
        "ERR_INVALID_ADVISOR_STATE",
        409,
    )
    validate_error(
        api_client.finalize_departure(advisor["id"], compliance()),
        "ERR_INVALID_ADVISOR_STATE",
        409,
    )
    validate_error(
        api_client.post_settlement_run(run["id"], controller("ctrl-2")),
        "ERR_INVALID_RUN_STATE",
        409,
    )

    unchanged = read_advisor(advisor["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == advisor["version"]

    still_open = read_run(run["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["posted_by_user_id"] is None


def test_a_rejected_or_revoked_credential_accepts_no_further_decision():
    """PRD §3.3: "Applying `VERIFY` or `REJECT` to a row that is not `PENDING_REVIEW`, or
    `REVOKE` to a row that is not `VERIFIED`, is reported as
    `ERR_INVALID_CREDENTIAL_STATE`."

    Design: Corner/state_machines/corner_terminal_credential_states_accept_no_further_decision
    """
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    rejected = file_credential(
        advisor["id"],
        training_cert_credential_payload(
            credential_number="TRN-BAD-1",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
        ),
    )
    validate_success(
        api_client.decide_compliance_credential(
            rejected["id"],
            credential_decision_payload(
                "REJECT", note="Certificate could not be authenticated"
            ),
            compliance(),
        )
    )

    revoked = file_credential(
        advisor["id"],
        eo_policy_credential_payload(
            credential_number="EO-99881",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
            coverage_amount_cents=100_000_000,
        ),
    )
    verified = validate_success(
        api_client.decide_compliance_credential(
            revoked["id"], credential_decision_payload("VERIFY"), compliance()
        )
    )
    verified_at = verified["verified_at"]
    validate_success(
        api_client.decide_compliance_credential(
            revoked["id"],
            credential_decision_payload("REVOKE", note="Carrier cancelled the policy"),
            compliance(),
        )
    )

    validate_error(
        api_client.decide_compliance_credential(
            rejected["id"], credential_decision_payload("VERIFY"), compliance()
        ),
        "ERR_INVALID_CREDENTIAL_STATE",
        409,
    )
    validate_error(
        api_client.decide_compliance_credential(
            revoked["id"], credential_decision_payload("VERIFY"), compliance()
        ),
        "ERR_INVALID_CREDENTIAL_STATE",
        409,
    )

    assert read_credential(rejected["id"])["status"] == "REJECTED"
    still_revoked = read_credential(revoked["id"])
    assert still_revoked["status"] == "REVOKED"
    assert still_revoked["verified_at"] == verified_at
    assert read_advisor(advisor["id"])["status"] == "DRAFT"


def test_each_activation_precondition_is_enforced_on_its_own():
    """PRD §3.2: "A `DRAFT` advisor becomes `ACTIVE` only when the advisor has exactly one
    agreement in status `ACTIVE` — otherwise `ERR_ACTIVE_AGREEMENT_MISSING` (HTTP 422) — and
    holds three separate verified credentials, each with an in-force window meaning that
    `effective_on` is at or before the logical clock and the clock is strictly before
    `expires_on`: a `SELLER_OF_TRAVEL` registration whose `jurisdiction_state_code` equals
    the advisor's `seller_of_travel_state`, failing which the attempt is rejected with
    `ERR_SELLER_OF_TRAVEL_INVALID`; an `EO_POLICY` whose `coverage_amount_cents` is at least
    one hundred million cents, that is one million dollars of per-occurrence
    errors-and-omissions cover, failing which `ERR_EO_COVERAGE_INSUFFICIENT`; and a
    `TRAINING_CERT`, failing which `ERR_TRAINING_CERT_MISSING`."

    Design: Corner/state_machines/corner_activation_preconditions_enforced_one_by_one
    """
    schedule = new_split_schedule(
        name="Standard 2026",
        tiers=[
            {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
            {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
        ],
        platform_fee_tiers=[{"min_share_cents": 0, "fee_pct": 0.05}],
        chargeback_retention_pct=0.10,
    )
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    advisor_id = advisor["id"]

    validate_error(
        api_client.activate_advisor(advisor_id, ops()),
        "ERR_ACTIVE_AGREEMENT_MISSING",
        422,
    )

    sign_agreement(advisor_id, schedule["id"], effective_date="2026-01-01")
    validate_error(
        api_client.activate_advisor(advisor_id, ops()),
        "ERR_SELLER_OF_TRAVEL_INVALID",
        422,
    )

    registration = file_credential(
        advisor_id,
        seller_of_travel_credential_payload(
            jurisdiction_state_code="NY",
            credential_number="NY-SOT-40118",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
        ),
    )
    decide_credential(registration["id"], "VERIFY")

    thin_policy = file_credential(
        advisor_id,
        eo_policy_credential_payload(
            credential_number="EO-LOW-1",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
            coverage_amount_cents=50_000_000,
        ),
    )
    verified_thin = decide_credential(thin_policy["id"], "VERIFY")
    assert verified_thin["coverage_amount_cents"] == 50_000_000

    validate_error(
        api_client.activate_advisor(advisor_id, ops()),
        "ERR_EO_COVERAGE_INSUFFICIENT",
        422,
    )

    decide_credential(
        thin_policy["id"], "REVOKE", note="Replaced by a higher-limit policy"
    )
    full_policy = file_credential(
        advisor_id,
        eo_policy_credential_payload(
            credential_number="EO-99881",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
            coverage_amount_cents=100_000_000,
        ),
    )
    decide_credential(full_policy["id"], "VERIFY")

    validate_error(
        api_client.activate_advisor(advisor_id, ops()),
        "ERR_TRAINING_CERT_MISSING",
        422,
    )

    training = file_credential(
        advisor_id,
        training_cert_credential_payload(
            credential_number="TRN-2026-A",
            effective_on="2026-01-01",
            expires_on="2027-01-01",
        ),
    )
    decide_credential(training["id"], "VERIFY")

    activated = validate_success(api_client.activate_advisor(advisor_id, ops()))
    assert activated["status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == "ops-1"
    assert activated["eo_coverage_verified_cents"] == 100_000_000
    assert activated["split_tier_provisional"] == 1
    assert activated["split_tier_final"] == 1


def test_revoking_the_last_registration_suspends_the_advisor_without_touching_its_work():
    """PRD §3.3: "When the revoked row was a `SELLER_OF_TRAVEL` registration and, after the
    revocation, the owning advisor has no remaining credential that is a `SELLER_OF_TRAVEL`,
    is `VERIFIED`, matches the advisor's `seller_of_travel_state` and is in force at the
    logical clock, then that advisor — if currently `ACTIVE` — is moved from `ACTIVE` to
    `SUSPENDED` by the system, with the advisor's `version` incrementing by 1."

    Design: Corner/state_machines/corner_revoking_last_registration_suspends_the_advisor
    """
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=new_split_schedule(),
        suppliers=[supplier],
    )
    advisor_id = ctx["advisor"]["id"]
    client = new_client(
        advisor_id,
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    booking = new_booking(
        advisor_id,
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )

    revoked = decide_credential(
        ctx["credentials"]["seller_of_travel"]["id"],
        "REVOKE",
        note="State registration surrendered",
    )
    assert revoked["status"] == "REVOKED"
    assert read_advisor(advisor_id)["status"] == "SUSPENDED"

    kept = read_booking(booking["id"])
    assert kept["booking_status"] == "SUBMITTED"
    assert kept["expected_commission_cents"] == 100_000
    assert read_advisor(advisor_id)["production_ytd_provisional_cents"] == 100_000

    validate_error(
        api_client.create_booking(
            create_booking_payload(
                advisor_id,
                supplier["id"],
                client["id"],
                channel="SUPPLIER_DIRECT",
                payment_method="MERCHANT_DIRECT",
                gross_sale_cents=500_000,
                travel_start_date="2026-11-01",
                travel_end_date="2026-11-10",
            ),
            make_advisor_headers(advisor_id),
        ),
        "ERR_ADVISOR_NOT_ACTIVE",
        409,
    )


def test_a_second_post_of_the_same_run_is_refused():
    """PRD §3.8: "An empty run is not an error: a run whose `statement_count` is 0 may be
    posted, and it transitions straight through to `CLOSED` within the same request."

    Design: Corner/state_machines/corner_second_post_of_the_same_settlement_run_is_rejected
    """
    run = open_run("2026-06")
    calculated = calculate_run(run["id"], "ctrl-1")
    assert calculated["status"] == "CALCULATED"
    assert calculated["statement_count"] == 0

    posted = validate_success(
        api_client.post_settlement_run(run["id"], controller("ctrl-2"))
    )
    assert posted["status"] == "CLOSED"
    assert posted["posted_by_user_id"] == "ctrl-2"

    validate_error(
        api_client.post_settlement_run(run["id"], controller("ctrl-2")),
        "ERR_INVALID_RUN_STATE",
        409,
    )

    settled = read_run(run["id"])
    assert settled["status"] == "CLOSED"
    assert settled["posted_by_user_id"] == "ctrl-2"
    assert settled["version"] == posted["version"]


def test_paying_the_last_statement_bubbles_the_run_to_closed():
    """PRD §3.8: "Finally the run's own terminal state bubbles up from its children rather
    than being requested: once every statement belonging to a `POSTED` run has reached
    `PAID`, the run itself transitions `POSTED` to `CLOSED` and its `version` increments."

    Design: Corner/state_machines/corner_run_closes_when_last_statement_is_paid
    """
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=new_split_schedule(
            name="Standard 2026",
            tiers=[
                {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
                {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
            ],
            platform_fee_tiers=[
                {"min_share_cents": 0, "fee_pct": 0.05},
                {"min_share_cents": 1_000_000, "fee_pct": 0.03},
            ],
            chargeback_retention_pct=0.10,
        ),
        suppliers=[supplier],
    )
    advisor_id = ctx["advisor"]["id"]
    client = new_client(
        advisor_id,
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    booking = new_booking(
        advisor_id,
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-05-01",
        travel_end_date="2026-05-10",
    )
    confirm_booking(booking["id"], supplier["id"])

    set_clock("2026-10-05T00:00:00Z")
    record_receipt(booking["id"], supplier["id"], 100_000, "2026-10-05")
    run = calculate_run(open_run("2026-10")["id"], "ctrl-1")
    assert run["statement_count"] == 1
    posted_run = validate_success(
        api_client.post_settlement_run(run["id"], controller("ctrl-2"))
    )
    assert posted_run["status"] == "POSTED"

    statement = statements_for_run(run["id"])[0]
    assert statement["advisor_share_cents"] == 70_000
    assert statement["platform_fee_cents"] == 3_500
    assert statement["marketing_fund_cents"] == 0
    assert statement["net_payout_cents"] == 66_500

    paid = pay_statement(statement["id"], payment_reference="ACH-2026-10-0001")
    assert paid["status"] == "PAID"
    assert paid["paid_at"].startswith("2026-10-05T00:00:00")

    closed = read_run(run["id"])
    assert closed["status"] == "CLOSED"
    assert closed["version"] > posted_run["version"]
    assert read_advisor(advisor_id)["lifetime_settled_share_cents"] == 70_000
    assert read_booking(booking["id"])["statement_id"] == statement["id"]
