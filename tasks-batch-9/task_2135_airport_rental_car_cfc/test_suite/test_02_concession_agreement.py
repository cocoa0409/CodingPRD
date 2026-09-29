"""The concession agreement and its two independent status axes."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    ApiErrorId,
    UNKNOWN_UUID,
    assert_agreement,
    assert_bare_uuid,
    assert_iso8601_millis,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_drafted_agreement_starts_with_every_ledger_field_at_zero(api):
    """PRD §3.2: "A freshly drafted agreement begins with `contract_status` of `DRAFT` and
    `compliance_status` of `COMPLIANT`, and with every ledger field at zero:
    `gross_revenue_ytd_cents`, `transaction_days_ytd`, `accepted_report_count`,
    `percentage_rent_accrued_cents`, `rent_billed_to_date_cents`, `last_installment_cents`,
    `mag_shortfall_cents`, `counter_units_assigned` and `fleet_stalls_allocated` all start at
    0, and `rent_tier` starts at `MAG_FLOOR`."
    PRD §3.2: "Drafting an agreement raises the named brand's `agreement_count` by 1."

    Design: Corner/entities/agreement_creation_zeroes_every_computed_ledger_field
    """
    facility = fx.create_facility(api)
    brand = fx.create_concessionaire(api, facility["id"])

    agreement = validate_success(
        api.create_agreement(f.agreement_payload(facility["id"], brand["id"]), ADMIN), 201
    )

    assert_agreement(agreement)
    for field in (
        "gross_revenue_ytd_cents",
        "transaction_days_ytd",
        "accepted_report_count",
        "percentage_rent_accrued_cents",
        "rent_billed_to_date_cents",
        "last_installment_cents",
        "mag_shortfall_cents",
        "counter_units_assigned",
        "fleet_stalls_allocated",
    ):
        assert agreement[field] == 0, f"{field} must start at 0, got {agreement[field]}"
    assert agreement["rent_tier"] == "MAG_FLOOR"
    assert agreement["contract_status"] == "DRAFT"
    assert agreement["compliance_status"] == "COMPLIANT"

    brand_after = validate_success(api.get_concessionaire(brand["id"], ADMIN))
    assert brand_after["agreement_count"] == 1, (
        "drafting one agreement must raise the brand's agreement_count to 1"
    )


def test_agreement_identity_fields_are_server_minted(api):
    """PRD §2.4: "Every resource carries a server-minted `id` that is a UUID string with no
    type prefix; clients never supply an `id`. Every resource also carries a `created_at`
    timestamp in ISO 8601 UTC form with three fractional digits, recorded when the row was
    inserted."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the current
    instant on every mutation, and `version`, an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/agreement_system_fields_are_server_minted_uuid_and_version_one
    """
    facility = fx.create_facility(api)
    brand = fx.create_concessionaire(api, facility["id"])

    agreement = validate_success(
        api.create_agreement(f.agreement_payload(facility["id"], brand["id"]), ADMIN), 201
    )

    assert_bare_uuid(agreement["id"])
    assert agreement["version"] == 1, (
        f"version must start at 1, got {agreement['version']}"
    )
    assert_iso8601_millis(agreement["created_at"])
    assert_iso8601_millis(agreement["updated_at"])


def test_agreement_with_unknown_rent_settlement_basis_is_rejected(api):
    """PRD §3.2: "and `rent_settlement_basis`, an enumeration of exactly `CUMULATIVE_YTD` and
    `MONTHLY_STANDALONE` that selects which of two very different rent variants governs the
    agreement for its whole life."
    PRD §2.6: "Request shape: every required input field is present, every value has the
    declared type, every enum-typed value is a legal member of its enumeration, every integer
    satisfies its declared range, every date parses as `YYYY-MM-DD`, and pagination stays
    within its bounds; otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/agreement_invalid_rent_settlement_basis_enum_returns_invalid_request
    """
    facility = fx.create_facility(api)
    brand = fx.create_concessionaire(api, facility["id"])

    response = api.create_agreement(
        f.agreement_payload(
            facility["id"], brand["id"], rent_settlement_basis="QUARTERLY_BLEND"
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _rows, meta = validate_paginated(
        api.list_agreements(ADMIN, params={"facility_id": facility["id"]})
    )
    assert meta["total_count"] == 0, "the rejected draft must create no agreement"


def test_agreement_naming_unknown_concessionaire_is_rejected(api):
    """PRD §2.5: "Foreign keys supplied in a request body are resolved the same way and with
    the same error codes, in the order in which the endpoint's input fields are listed in §3's
    description of that operation."
    PRD §2.5: "`concessionaire_id` yields `ERR_CONCESSIONAIRE_NOT_FOUND`"

    Design: Corner/entities/agreement_with_unknown_concessionaire_id_returns_not_found
    """
    facility = fx.create_facility(api)

    response = api.create_agreement(
        f.agreement_payload(facility["id"], UNKNOWN_UUID), ADMIN
    )

    validate_error(response, ApiErrorId.ERR_CONCESSIONAIRE_NOT_FOUND.value, 404)


def test_executing_an_already_active_agreement_is_rejected(api):
    """PRD §3.2: "Executing a drafted agreement carries `contract_status` from `DRAFT` to
    `ACTIVE`. It requires the agreement to be in `DRAFT` and requires `term_start_date` to be
    strictly earlier than `term_end_date`; the brand's `agreement_count` is not touched,
    because it was already raised when the agreement was drafted."
    PRD §2.6: "State: the target resource sits in a from-state that the requested transition
    declares, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/execute_an_already_active_agreement_returns_invalid_state
    """
    scenario = fx.setup_active_agreement(api)
    agreement = scenario["agreement"]
    version_before = agreement["version"]

    response = api.execute_agreement(agreement["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_agreement(agreement["id"], ADMIN))
    assert after["contract_status"] == "ACTIVE"
    assert after["version"] == version_before, (
        "a rejected execute is not a mutation and must not advance version"
    )


def test_reinstate_returns_the_agreement_to_active(api):
    """PRD §3.2: "Reinstating a suspended agreement carries it from `SUSPENDED` back to
    `ACTIVE`, closing the `ACTIVE → SUSPENDED → ACTIVE` loop, which an agreement may cycle
    through any number of times."
    PRD §3.2: "Each of these three lifecycle actions advances the agreement's `version` by 1,
    and all three are reserved to `FacilityAdmin`."

    Design: Corner/endpoints/reinstate_action_endpoint_restores_active_contract_status
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id = scenario["agreement"]["id"]
    suspended = validate_success(api.suspend_agreement(agreement_id, ADMIN))

    response = api.reinstate_agreement(agreement_id, ADMIN)
    reinstated = validate_success(response, 200)

    assert reinstated["contract_status"] == "ACTIVE"
    assert reinstated["compliance_status"] == "COMPLIANT", (
        "reinstatement must leave the compliance axis untouched"
    )
    assert reinstated["version"] == suspended["version"] + 1, (
        f"reinstate must advance version by exactly 1: "
        f"{suspended['version']} -> {reinstated['version']}"
    )


def test_agreement_version_rises_by_one_per_mutation(api):
    """PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the current
    instant on every mutation, and `version`, an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of that row."
    PRD §3.2: "Each of these three lifecycle actions advances the agreement's `version` by 1,
    and all three are reserved to `FacilityAdmin`."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_increments_by_one_on_every_mutation
    """
    facility = fx.create_facility(api)
    brand = fx.create_concessionaire(api, facility["id"])

    created = validate_success(
        api.create_agreement(f.agreement_payload(facility["id"], brand["id"]), ADMIN), 201
    )
    executed = validate_success(api.execute_agreement(created["id"], ADMIN))
    suspended = validate_success(api.suspend_agreement(created["id"], ADMIN))
    reinstated = validate_success(api.reinstate_agreement(created["id"], ADMIN))

    assert created["version"] == 1, f"creation must mint version 1, got {created['version']}"
    assert executed["version"] == 2, f"execute must reach version 2, got {executed['version']}"
    assert suspended["version"] == 3, f"suspend must reach version 3, got {suspended['version']}"
    assert reinstated["version"] == 4, (
        f"reinstate must reach version 4, got {reinstated['version']}"
    )
    assert reinstated["updated_at"] > reinstated["created_at"], (
        "updated_at must be refreshed past created_at by the reinstate mutation"
    )


def test_clock_past_term_end_expires_an_active_agreement(api):
    """PRD §3.2: "When the logical clock is advanced past an agreement's `term_end_date` —
    that is, when the clock's calendar date is strictly later than `term_end_date` — an
    agreement in `ACTIVE` moves to `EXPIRED`, and an agreement in `SUSPENDED` moves to
    `TERMINATED`."
    PRD §3.2: "Agreements swept into either terminal state are counted in the clock response's
    `expired_agreement_count`."
    PRD §3.2: "Neither axis ever reads or writes the other: an `ACTIVE` agreement stays
    `ACTIVE` while it is `DELINQUENT`, and executing or suspending an agreement leaves
    `compliance_status` untouched."

    Design: Corner/state_machines/clock_advance_past_term_end_expires_an_active_agreement
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id = scenario["agreement"]["id"]

    summary = validate_success(
        api.set_clock(f.clock_payload("2027-01-01T00:00:00Z"), ADMIN)
    )

    assert summary["expired_agreement_count"] == 1, (
        f"the sweep must count one agreement, got {summary['expired_agreement_count']}"
    )
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["contract_status"] == "EXPIRED"
    assert agreement["compliance_status"] == "COMPLIANT", (
        "expiry must not disturb the independent compliance axis"
    )
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["current_utc"] == "2027-01-01T00:00:00Z"


def test_audit_acceptance_moves_compliance_without_touching_contract_status(api):
    """PRD §3.5: "`revenue_variance_cents` is set to `audited_gross_revenue_cents` minus
    `reported_gross_revenue_cents`, which may be negative when the operator over-reported;
    `variance_assessment_cents` is the greater of zero and `revenue_variance_cents`,
    multiplied by the agreement's `percentage_rent_rate_bps`, divided by 10,000 and rounded
    half up"
    PRD §3.5: "When `variance_assessment_cents` came out greater than zero, the agreement's
    `compliance_status` moves to `COVENANT_BREACH`, from either `COMPLIANT` or `DELINQUENT`."
    PRD §3.2: "Neither axis ever reads or writes the other: an `ACTIVE` agreement stays
    `ACTIVE` while it is `DELINQUENT`, and executing or suspending an agreement leaves
    `compliance_status` untouched."

    Design: Difficulty/non_linear_state_machine/agreement_contract_and_compliance_axes_advance_independently
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report_under_audit(
        api,
        agreement_id,
        operator,
        period_year=2026,
        period_month=5,
        reported_gross_revenue_cents=4_000_000,
        reported_on_airport_transaction_days=800,
    )
    validate_success(api.suspend_agreement(agreement_id, ADMIN))

    accepted = validate_success(
        api.accept_report(
            report["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=6_000_000,
                audited_on_airport_transaction_days=800,
            ),
            AUDITOR,
        )
    )

    assert accepted["revenue_variance_cents"] == 2_000_000
    assert accepted["variance_assessment_cents"] == 200_000, (
        "a 2,000,000 cent under-report at 1000 bps is assessed at 200,000 cents"
    )
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["compliance_status"] == "COVENANT_BREACH"
    assert agreement["contract_status"] == "SUSPENDED", (
        "the acceptance must not move the contractual axis"
    )
    assert agreement["gross_revenue_ytd_cents"] == 6_000_000


def test_reinstate_leaves_covenant_breach_standing(api):
    """PRD §3.2: "Reinstating a suspended agreement carries it from `SUSPENDED` back to
    `ACTIVE`, closing the `ACTIVE → SUSPENDED → ACTIVE` loop, which an agreement may cycle
    through any number of times."
    PRD §3.2: "Neither axis ever reads or writes the other: an `ACTIVE` agreement stays
    `ACTIVE` while it is `DELINQUENT`, and executing or suspending an agreement leaves
    `compliance_status` untouched."
    PRD §3.5: "The epilogue is identical for both variants. The agreement's
    `percentage_rent_accrued_cents` is set to the year-to-date percentage rent; its
    `rent_billed_to_date_cents` rises by the installment; its `last_installment_cents` is set
    to the installment; its `mag_shortfall_cents` is set to the greater of zero and the
    minimum guarantee to date minus the year-to-date percentage rent; and its `rent_tier`
    becomes `PERCENTAGE` when the year-to-date percentage rent is strictly greater than the
    minimum guarantee to date, and `MAG_FLOOR` otherwise."

    Design: Difficulty/non_linear_state_machine/agreement_contract_and_compliance_axes_advance_independently
    """
    scenario = fx.setup_active_agreement(api)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    report = fx.create_report_under_audit(
        api,
        agreement_id,
        operator,
        period_year=2026,
        period_month=5,
        reported_gross_revenue_cents=4_000_000,
        reported_on_airport_transaction_days=800,
    )
    validate_success(api.suspend_agreement(agreement_id, ADMIN))
    validate_success(
        api.accept_report(
            report["id"],
            f.accept_report_payload(
                audited_gross_revenue_cents=6_000_000,
                audited_on_airport_transaction_days=800,
            ),
            AUDITOR,
        )
    )

    reinstated = validate_success(api.reinstate_agreement(agreement_id, ADMIN))

    assert reinstated["contract_status"] == "ACTIVE"
    assert reinstated["compliance_status"] == "COVENANT_BREACH", (
        "reinstatement moves only the contractual axis; the breach must survive"
    )
    assert reinstated["rent_billed_to_date_cents"] == 1_000_000, (
        "the 1,000,000 cent monthly guarantee floor was billed by the acceptance"
    )
    assert reinstated["rent_tier"] == "MAG_FLOOR"
    assert reinstated["mag_shortfall_cents"] == 400_000
