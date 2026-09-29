"""Role exclusivity and the ownership rung that separates identity from role."""

from test_helpers import fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import (
    amount_payload,
    create_custodian_payload,
    create_depository_payload,
    create_runoff_forecast_payload,
    create_safekeeping_receipt_payload,
    decide_payload,
    projected_window,
    set_clock_payload,
)
from test_helpers.fixtures import OFFICER, REGULATOR
from test_helpers.test_users import (
    make_custodian_headers,
    make_public_unit_treasurer_headers,
)


def test_no_role_may_reach_across_into_another_roles_exclusive_operation(client):
    """The regulator cannot register a bank or move the clock, the treasurer cannot register a bank,
    and the officer can neither decide the package it filed nor register a custodian: five cross-role
    attempts, five identical role refusals, and the operation still works for the one role that owns
    it.

    PRD: "2. **Role authorisation** — the acting role appears in the endpoint's authorised-role
    list, else `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."
    PRD: "- A `StateRegulator` is the state treasurer's office or banking department. It qualifies
    and approves depositories, administers pooled collateral programs, registers public units and
    custodians, confirms safekeeping receipts, declares collateral ineligible, and suspends
    depositories or terminates executed agreements."
    PRD: "- A `SystemOperator` is the operational automation identity. It drives the logical clock
    and the daily margin-call sweep and feeds market prices from the pricing vendor. It holds no
    supervisory and no banking authority."
    PRD: "| POST | /depositories | Register a bank as a candidate public-funds depository |
    BankCollateralOfficer |"
    PRD: "| POST | /custodians | Register a tri-party custodian, pending state approval |
    StateRegulator |"
    PRD: "| POST | /_clock/set_current_utc | Set the service's logical clock | SystemOperator |"
    PRD: "| POST | /qualification-reviews/{id}/decide | Approve or deny the depository for public
    unit deposits | StateRegulator |"

    Design: Corner/RBAC/roles_cannot_perform_each_others_exclusive_operations
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository, review = fixtures.create_depository_under_review(client)
    treasurer = make_public_unit_treasurer_headers(public_unit["id"])

    treasurer_registers = client.create_depository(
        create_depository_payload(name="Treasurer Bank"), treasurer
    )
    validate_error(treasurer_registers, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    regulator_registers = client.create_depository(
        create_depository_payload(name="Regulator Bank"), REGULATOR
    )
    validate_error(regulator_registers, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    officer_decides = client.decide_qualification_review(
        review["id"], decide_payload("APPROVE"), OFFICER
    )
    validate_error(officer_decides, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    officer_registers_custodian = client.create_custodian(
        create_custodian_payload(name="Officer Custody"), OFFICER
    )
    validate_error(
        officer_registers_custodian, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403
    )

    regulator_moves_clock = client.set_clock(
        set_clock_payload("2026-09-01T00:00:00Z"), REGULATOR
    )
    validate_error(regulator_moves_clock, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    decided = fixtures.decide_review(client, review["id"], decision="APPROVE")
    assert decided["status"] == "APPROVED"
    assert decided["decided_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    approved = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert approved["approval_status"] == "APPROVED"

    _depositories, meta = validate_paginated(client.list_depositories(REGULATOR))
    assert meta["total_count"] == 1


def test_a_valid_role_is_not_a_licence_over_another_principals_rows(client):
    """A second treasurer holding a perfectly valid role header cannot credit or forecast against a
    foreign account — even with the right version pinned — and a second custodian cannot issue a
    receipt under an agreement held elsewhere, while the owning custodian's identical request is
    accepted.

    PRD: "3. **Entity-backed ownership** — an entity-backed caller owns the target, else
    `ERR_NOT_RESOURCE_OWNER`. This rung applies to exactly ten operations: opening a deposit account,
    crediting a deposit, debiting a withdrawal, filing a runoff forecast, recording a signature,
    requesting an agreement amendment, acknowledging a substitution as custodian, settling a
    substitution as custodian, issuing a safekeeping receipt, and reading an account's coverage
    report."
    PRD: "When `X-User-Role` is `Custodian`, `X-User-ID` is the `id` of the acting `Custodian`
    record; ownership checks on any resource that references a `Custodian` compare the resource's
    custodian foreign-key field to `X-User-ID`, so a custodian may acknowledge, settle or issue
    receipts only against pledge agreements whose `custodian_id` equals its own `X-User-ID`."
    PRD: "When `X-User-Role` is `PublicUnitTreasurer`, `X-User-ID` is the `id` of the acting
    `PublicUnit` record; ownership checks compare the `public_unit_id` on the target deposit account
    (or, for a runoff forecast, on the account the forecast projects, or, for a signature or
    amendment request, on the pledge agreement's beneficiary deposit account) to `X-User-ID`."
    PRD: "A violation of either ownership rule is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP
    403)."
    PRD: "6. **Version pinning** — the three checks of §2.6, each returning its own error
    identifier."
    PRD: "The receipt is created with `confirmation_status` `ISSUED`, and `confirmed_by_user_id` and
    `confirmed_at` null."
    PRD: "When `discrepancy_par_cents` is zero **and** `reported_asset_count` equals
    `ledger_asset_count`, the receipt moves to `CONFIRMED`; when either the discrepancy is non-zero
    or the counts disagree, it moves to `EXCEPTION`."

    Design: Corner/RBAC/entity_backed_principal_cannot_act_on_another_principals_rows
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    stranger_unit = fixtures.create_public_unit(client, name="Vale County", unit_type="COUNTY")
    stranger_custodian = fixtures.create_approved_custodian(
        client, name="Beta Custody", custodian_type="FHLB", tri_party_capable=True
    )
    owner = make_public_unit_treasurer_headers(perimeter["public_unit_id"])
    stranger = make_public_unit_treasurer_headers(stranger_unit["id"])
    account_version = fixtures.account_version(client, perimeter["account_id"], owner)

    foreign_deposit = client.create_deposit(
        perimeter["account_id"], amount_payload(5_000_000), stranger
    )
    validate_error(foreign_deposit, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    foreign_forecast = client.create_runoff_forecast(
        create_runoff_forecast_payload(
            perimeter["account_id"],
            DEFAULT_CLOCK_UTC,
            "2026-08-31T00:00:00Z",
            [projected_window(DEFAULT_CLOCK_UTC, "2026-08-31T00:00:00Z", 100_000_000)],
            account_version,
        ),
        stranger,
    )
    validate_error(foreign_forecast, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    foreign_receipt = client.create_safekeeping_receipt(
        create_safekeeping_receipt_payload(
            perimeter["agreement_id"], 0, 0, receipt_number="RC-B"
        ),
        make_custodian_headers(stranger_custodian["id"]),
    )
    validate_error(foreign_receipt, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], owner), 200
    )
    assert account["ledger_balance_cents"] == 100_000_000
    assert account["version"] == account_version
    quiet_unit = get_success_data(
        client.get_public_unit(stranger_unit["id"], REGULATOR), 200
    )
    assert quiet_unit["total_deposit_balance_cents"] == 0

    owned_receipt = fixtures.issue_receipt(
        client, perimeter["agreement_id"], perimeter["custodian_id"], 0, 0, receipt_number="RC-A"
    )
    assert owned_receipt["confirmation_status"] == "ISSUED"
    assert owned_receipt["ledger_par_cents"] == 0
    assert owned_receipt["ledger_asset_count"] == 0
    assert owned_receipt["discrepancy_par_cents"] == 0

    confirmed = fixtures.confirm_receipt(client, owned_receipt["id"])
    assert confirmed["confirmation_status"] == "CONFIRMED"

    receipts, meta = validate_paginated(
        client.list_agreement_safekeeping_receipts(
            perimeter["agreement_id"], make_custodian_headers(perimeter["custodian_id"])
        )
    )
    assert meta["total_count"] == 1
    assert receipts[0]["receipt_number"] == "RC-A"
