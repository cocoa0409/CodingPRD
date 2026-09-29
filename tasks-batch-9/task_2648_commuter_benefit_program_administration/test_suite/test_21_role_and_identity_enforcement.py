"""Role, ownership and duty-segregation enforcement.

Three enforcement layers meet in this module: the per-endpoint authorized-role
list that every caller must appear in, the per-row ownership gate that applies
to the one entity-backed role, and the two workflows that compare the acting
operator identifier against an identifier recorded during an earlier step of the
same workflow.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_EMPLOYEE_SCOPE_VIOLATION,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_account_conservation,
    assert_append_only_common_fields,
    assert_election_axes,
    assert_invoice_totals,
    assert_mutable_common_fields,
)
from test_helpers.constants import REGION_AUS
from test_helpers.test_users import (
    PROGRAM_ADMIN,
    make_compliance_reviewer_headers,
    make_employee_headers,
    make_order_desk_headers,
    make_payroll_processor_headers,
)


# =============================================================================
# The permit half of the matrix: every role succeeds at its own operations.
# =============================================================================
def test_01_order_desk_curates_the_catalogue_and_opens_a_procurement_batch(api):
    """PRD §2.1: "An `OrderDesk` is the transit media procurement operator: it curates
    the regional media catalogue, assembles procurement batches against the order
    cutoff calendar, seals and releases them, records shipments, and reissues lost or
    undelivered media."
    PRD §3.5: "A new product opens in `status` `ACTIVE`."
    PRD §3.5: "A new batch opens in `status` `OPEN` with `line_count`, `subtotal_cents`,
    `discount_cents` and `total_cents` all zero and both `sealed_by_user_id` and
    `released_by_user_id` null, as well as `sealed_at`."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_and_shared_operations
    """
    program = fixtures.make_program_with_participant(api, region_code=REGION_AUS)
    desk = make_order_desk_headers("desk-permit")

    media = validate_success(
        api.create_transit_media(
            f.transit_media_payload(
                sku="AUS-PM",
                media_type="SMART_CARD_LOAD",
                region_code=REGION_AUS,
                eligible_category_type="TRANSIT_PASS",
                unit_price_cents=3000,
            ),
            desk,
        ),
        expected_status=201,
    )
    assert media["status"] == "ACTIVE", "a new catalogue product opens ACTIVE"
    assert media["unit_price_cents"] == 3000
    assert_mutable_common_fields(media, expected_version=1)

    batch = validate_success(
        api.create_order_batch(
            f.order_batch_payload(program["window"]["id"], REGION_AUS), desk
        ),
        expected_status=201,
    )
    assert batch["status"] == "OPEN"
    assert batch["line_count"] == 0
    assert batch["subtotal_cents"] == 0
    assert batch["discount_cents"] == 0
    assert batch["total_cents"] == 0
    assert batch["sealed_by_user_id"] is None
    assert batch["released_by_user_id"] is None
    assert batch["sealed_at"] is None
    assert_mutable_common_fields(batch, expected_version=1)


def test_02_compliance_reviewer_runs_the_ordinance_assessment(api):
    """PRD §3.9: "Either a `ProgramAdmin` or a `ComplianceReviewer` runs one by supplying
    an `assessment_month` in the four-digit-year, hyphen, two-digit-month shape."
    PRD §3.9: "the employees of this employer whose `status` is `ACTIVE`, whose
    `work_region_code` equals the employer's own `region_code`, and whose `hire_date` falls
    at or before that month-end boundary"
    PRD §3.9: "the employer's `transit_group_limit_cents` at assessment time is snapshotted
    alongside it as `assessed_transit_group_limit_cents`"
    PRD §3.9: "If the employer's `region_code` is not one of the three covered
    jurisdictions — `US-CA-SFO`, `US-NY-NYC` and `US-WA-SEA` — the assessment records
    `mandate_status` `EXEMPT` with `finding` `EXEMPT_REGION_NOT_COVERED`; employers whose
    primary region is `US-IL-CHI` or `US-TX-AUS` fall here."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_and_shared_operations
    """
    program = fixtures.make_program_with_participant(api, region_code=REGION_AUS)

    assessment = validate_success(
        api.create_compliance_assessment(
            program["employer"]["id"],
            f.compliance_assessment_payload("2026-08"),
            make_compliance_reviewer_headers("rev-permit"),
        ),
        expected_status=201,
    )
    assert assessment["mandate_status"] == "EXEMPT"
    assert assessment["finding"] == "EXEMPT_REGION_NOT_COVERED"
    assert assessment["covered_employee_count"] == 1, (
        "the one ACTIVE employee reports for work in the employer's own region"
    )
    assert assessment["assessed_transit_group_limit_cents"] == 30000
    assert_append_only_common_fields(assessment)

    employer = fixtures.read_employer(api, program["employer"]["id"])
    assert employer["ordinance_mandate_status"] == "EXEMPT"


def test_03_employee_files_an_election_on_their_own_record(api):
    """PRD §3.3: "Either the electing `Employee` or a `ProgramAdmin` files an election."
    PRD §3.3: "The new row opens with `funding_status` `PENDING` and `change_count` at
    zero."
    PRD §3.4: "`excluded_amount_cents` is then the smallest of those four values: the
    requested `pretax_amount_cents`, the group headroom, the category cap, and the ratio
    cap."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_and_shared_operations
    """
    program = fixtures.make_program_with_participant(api, region_code=REGION_AUS)
    employee = program["employee"]
    account_version = fixtures.current_account_version(api, program["account"]["id"])

    election = validate_success(
        api.create_election(
            f.election_payload(
                employee["id"],
                program["window"]["id"],
                program["category"]["id"],
                account_version,
                pretax_amount_cents=4000,
                posttax_amount_cents=0,
            ),
            make_employee_headers(employee["id"]),
        ),
        expected_status=201,
    )
    assert election["employee_id"] == employee["id"]
    assert election["funding_status"] == "PENDING"
    assert election["change_count"] == 0
    assert election["excluded_amount_cents"] == 4000
    assert election["total_amount_cents"] == 4000
    assert election["posttax_spill_cents"] == 0


def test_04_payroll_processor_reads_the_election_collection(api):
    """PRD §2.1: "Once the caller is authenticated, the service confirms that the declared
    role appears in the authorized-role list of the endpoint being called; a role acting
    outside its remit is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.3: "`total_count` reports the number of rows matching the filters before the
    page window is applied"

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_and_shared_operations
    """
    program = fixtures.make_program_with_participant(api, region_code=REGION_AUS)
    fixtures.make_election(
        api,
        program["employee"]["id"],
        program["window"]["id"],
        program["category"]["id"],
        program["account"]["id"],
        pretax_amount_cents=4000,
    )

    rows, meta = validate_paginated(
        api.list_elections(make_payroll_processor_headers("pay-permit"))
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["pretax_amount_cents"] == 4000
    assert rows[0]["employee_id"] == program["employee"]["id"]


# =============================================================================
# The deny half of the matrix: a role outside the endpoint's list is refused.
# =============================================================================
def test_05_order_desk_cannot_register_an_employer_program(api):
    """PRD §2.1: "Once the caller is authenticated, the service confirms that the declared
    role appears in the authorized-role list of the endpoint being called; a role acting
    outside its remit is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.7: "The service therefore evaluates checks in a single fixed ladder, returning
    the first failure it encounters and never masking an earlier check with a later one."

    Design: Corner/rbac/roles_outside_an_endpoints_role_list_are_rejected
    """
    fixtures.make_draft_employer(api, PROGRAM_ADMIN, legal_name="Deny Matrix Co")

    validate_error(
        api.create_employer(
            f.employer_payload(legal_name="Desk Sneak Co", region_code=REGION_AUS),
            make_order_desk_headers("desk-intruder"),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    rows, meta = validate_paginated(api.list_employers(PROGRAM_ADMIN))
    assert meta["total_count"] == 1, "the refused create must not have persisted a row"
    assert rows[0]["legal_name"] == "Deny Matrix Co"


def test_06_payroll_processor_cannot_declare_a_benefit_category(api):
    """PRD §2.1: "Once the caller is authenticated, the service confirms that the declared
    role appears in the authorized-role list of the endpoint being called; a role acting
    outside its remit is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/roles_outside_an_endpoints_role_list_are_rejected
    """
    employer = fixtures.make_draft_employer(api, PROGRAM_ADMIN, region_code=REGION_AUS)

    validate_error(
        api.create_benefit_category(
            f.benefit_category_payload(employer["id"], category_type="PARKING"),
            make_payroll_processor_headers("pay-intruder"),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    _rows, meta = validate_paginated(api.list_benefit_categories(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, "the refused create must not have persisted a row"


def test_07_compliance_reviewer_cannot_lock_an_election_window(api):
    """PRD §2.1: "Once the caller is authenticated, the service confirms that the declared
    role appears in the authorized-role list of the endpoint being called; a role acting
    outside its remit is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.7: "The service therefore evaluates checks in a single fixed ladder, returning
    the first failure it encounters and never masking an earlier check with a later one."

    Design: Corner/rbac/roles_outside_an_endpoints_role_list_are_rejected
    """
    program = fixtures.make_program_with_participant(
        api, region_code=REGION_AUS, open_window=False
    )
    window = program["window"]
    assert window["status"] == "SCHEDULED"

    validate_error(
        api.lock_election_window(
            window["id"], make_compliance_reviewer_headers("rev-intruder")
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    after = fixtures.read_window(api, window["id"])
    assert after["status"] == "SCHEDULED", (
        "the role refusal must be reported before any state transition is attempted"
    )
    assert after["version"] == window["version"]


def test_08_program_admin_cannot_add_a_catalogue_product(api):
    """PRD §2.1: "Once the caller is authenticated, the service confirms that the declared
    role appears in the authorized-role list of the endpoint being called; a role acting
    outside its remit is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.5: "The `OrderDesk` maintains a catalogue of media products shared across
    employers."

    Design: Corner/rbac/roles_outside_an_endpoints_role_list_are_rejected
    """
    validate_error(
        api.create_transit_media(
            f.transit_media_payload(
                sku="ADMIN-SNEAK", media_type="SMART_CARD_LOAD", region_code=REGION_AUS
            ),
            PROGRAM_ADMIN,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    _rows, meta = validate_paginated(
        api.list_transit_media(make_order_desk_headers("desk-audit"))
    )
    assert meta["total_count"] == 0, "the refused create must not have persisted a row"


def test_09_program_admin_cannot_open_a_procurement_batch(api):
    """PRD §2.1: "Once the caller is authenticated, the service confirms that the declared
    role appears in the authorized-role list of the endpoint being called; a role acting
    outside its remit is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.5: "Procurement happens in batches, one per region per window."

    Design: Corner/rbac/roles_outside_an_endpoints_role_list_are_rejected
    """
    program = fixtures.make_program_with_participant(api, region_code=REGION_AUS)

    validate_error(
        api.create_order_batch(
            f.order_batch_payload(program["window"]["id"], REGION_AUS), PROGRAM_ADMIN
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    _rows, meta = validate_paginated(
        api.list_order_batches(make_order_desk_headers("desk-audit"))
    )
    assert meta["total_count"] == 0, "the refused create must not have persisted a row"


# =============================================================================
# The per-row ownership gate on the one entity-backed role.
# =============================================================================
def _program_with_two_participants(api):
    """One employer, one category, two enrolled employees each with an account."""
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        legal_name="Peer Scope Co",
        region_code=REGION_AUS,
    )
    employer = built["employer"]
    category = built["categories"][0]
    first = fixtures.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        account_overrides={"opening_rollover_cents": 2000},
        external_ref="AUS-SCOPE-A",
        work_region_code=REGION_AUS,
    )
    second = fixtures.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        account_overrides={"opening_rollover_cents": 2000},
        external_ref="AUS-SCOPE-B",
        work_region_code=REGION_AUS,
    )
    window = fixtures.make_open_window(api, employer["id"], PROGRAM_ADMIN)
    return {
        "employer": employer,
        "category": category,
        "first": first,
        "second": second,
        "window": window,
    }


def test_10_employee_cannot_read_a_peers_benefit_account(api):
    """PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting
    `Employee` row, and ownership checks compare the target resource's owning employee to
    that value."
    PRD §2.1: "A mismatch is rejected with `ERR_EMPLOYEE_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/employee_acting_on_another_employees_records_is_rejected
    """
    setup = _program_with_two_participants(api)
    first_headers = make_employee_headers(setup["first"]["employee"]["id"])

    validate_error(
        api.get_benefit_account(setup["second"]["account"]["id"], first_headers),
        ERR_EMPLOYEE_SCOPE_VIOLATION,
    )

    own = validate_success(
        api.get_benefit_account(setup["first"]["account"]["id"], first_headers)
    )
    assert own["employee_id"] == setup["first"]["employee"]["id"]
    assert own["available_balance_cents"] == 2000
    assert_account_conservation(own)


def test_11_employee_cannot_file_an_election_for_a_peer(api):
    """PRD §2.1: "This ownership gate guards exactly eight operations: `POST
    /benefits/elections`, `PATCH /benefits/elections/{election_id}`, `POST
    /benefits/elections/{election_id}/cancel`, `POST
    /benefits/media-orders/{order_id}/report-undelivered`, `POST
    /benefits/media-orders/{order_id}/confirm-delivery`, `POST
    /benefits/substantiation-claims`, `GET /benefits/benefit-accounts/{account_id}` and
    `GET /benefits/benefit-accounts/{account_id}/ledger-entries`."
    PRD §2.1: "Concretely: for an election the compared field is the election's
    `employee_id`"
    PRD §3.3: "an election created with `media_quantity` of zero, or with the field
    omitted altogether, opens in `NOT_REQUIRED`, because no media will ever be needed for
    it"

    Design: Corner/rbac/employee_acting_on_another_employees_records_is_rejected
    """
    setup = _program_with_two_participants(api)
    first_employee = setup["first"]["employee"]
    second = setup["second"]
    peer_account_version = fixtures.current_account_version(api, second["account"]["id"])

    validate_error(
        api.create_election(
            f.election_payload(
                second["employee"]["id"],
                setup["window"]["id"],
                setup["category"]["id"],
                peer_account_version,
                pretax_amount_cents=4000,
            ),
            make_employee_headers(first_employee["id"]),
        ),
        ERR_EMPLOYEE_SCOPE_VIOLATION,
    )

    _rows, meta = validate_paginated(api.list_elections(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, "the refused create must not have persisted a row"

    own_version = fixtures.current_account_version(api, setup["first"]["account"]["id"])
    own = validate_success(
        api.create_election(
            f.election_payload(
                first_employee["id"],
                setup["window"]["id"],
                setup["category"]["id"],
                own_version,
                pretax_amount_cents=4000,
            ),
            make_employee_headers(first_employee["id"]),
        ),
        expected_status=201,
    )
    assert own["employee_id"] == first_employee["id"]
    assert_election_axes(own, "PENDING", "NOT_REQUIRED")


def test_12_employee_cannot_read_a_peers_account_ledger(api):
    """PRD §2.1: "A mismatch is rejected with `ERR_EMPLOYEE_SCOPE_VIOLATION` (HTTP 403)."
    PRD §3.2: "When a non-zero opening balance is supplied, the account's very first
    ledger entry is written at creation with `entry_type` `ROLLOVER_IN` and a positive
    `amount_cents` equal to that opening balance, with `source_entity` `BenefitAccount`
    and `source_id` the account's own identifier, and the account's
    `available_balance_cents` is set accordingly."

    Design: Corner/rbac/employee_acting_on_another_employees_records_is_rejected
    """
    setup = _program_with_two_participants(api)
    second_headers = make_employee_headers(setup["second"]["employee"]["id"])

    validate_error(
        api.list_account_ledger_entries(
            setup["first"]["account"]["id"], second_headers
        ),
        ERR_EMPLOYEE_SCOPE_VIOLATION,
    )

    rows, meta = validate_paginated(
        api.list_account_ledger_entries(setup["second"]["account"]["id"], second_headers)
    )
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "ROLLOVER_IN"
    assert rows[0]["amount_cents"] == 2000
    assert rows[0]["balance_after_cents"] == 2000
    assert rows[0]["source_entity"] == "BenefitAccount"
    assert rows[0]["source_id"] == setup["second"]["account"]["id"]


# =============================================================================
# Segregation of duties: the second actor must differ from the recorded first.
# =============================================================================
def test_13_sealing_operator_cannot_release_the_batch_they_sealed(api):
    """PRD §2.1: "Releasing a sealed procurement batch requires that the acting `X-User-ID`
    differ from the batch's `sealed_by_user_id`, and reopening a card transaction that
    currently sits in a substantiated posture requires that the acting `X-User-ID` differ
    from that transaction's `approved_by_user_id`."
    PRD §2.1: "Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403);
    the two guarded operations are `POST /benefits/order-batches/{batch_id}/release` and
    `POST /benefits/card-transactions/{transaction_id}/reopen`."

    Design: Corner/rbac/batch_release_by_the_sealing_operator_is_rejected
    """
    chain = fixtures.make_procurement_chain(
        api,
        region_code=REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=3000,
        unit_price_cents=3000,
        seal_user_id="desk-sealer",
        stop_after="sealed",
    )
    batch = chain["batch"]
    assert batch["status"] == "SEALED"
    assert batch["sealed_by_user_id"] == "desk-sealer"
    assert_invoice_totals(
        batch, line_count=1, subtotal_cents=3075, discount_cents=0, total_cents=3075
    )

    validate_error(
        api.release_order_batch(batch["id"], make_order_desk_headers("desk-sealer")),
        ERR_SEGREGATION_OF_DUTIES,
    )

    after = fixtures.read_batch(api, batch["id"])
    assert after["status"] == "SEALED"
    assert after["released_by_user_id"] is None
    assert after["version"] == batch["version"]
    assert fixtures.read_media_order(api, chain["order"]["id"])["status"] == "PENDING"


def test_14_a_second_operator_releases_the_sealed_batch(api):
    """PRD §3.5: "It requires the batch to be `SEALED`, the acting `X-User-ID` to differ
    from the recorded `sealed_by_user_id`, and the governing window's `status` to be `OPEN`
    or `LOCKED`."
    PRD §3.5: "On success the batch moves `SEALED → RELEASED` with `released_by_user_id`
    recording the acting `X-User-ID`, every media line in the batch whose `status` is
    `PENDING` moves `PENDING → SUBMITTED`, the `fulfillment_status` of every election
    referenced by those lines is re-derived, and `OrderBatch.version` advances by 1
    alongside the `version` of every released line and every affected election."

    Design: Corner/rbac/batch_release_by_the_sealing_operator_is_rejected
    """
    chain = fixtures.make_procurement_chain(
        api,
        region_code=REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=3000,
        unit_price_cents=3000,
        seal_user_id="desk-sealer",
        stop_after="sealed",
    )
    sealed = chain["batch"]

    released = validate_success(
        api.release_order_batch(
            sealed["id"], make_order_desk_headers("desk-releaser")
        )
    )
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == "desk-releaser"
    assert released["sealed_by_user_id"] == "desk-sealer"
    assert released["version"] == sealed["version"] + 1
    assert_invoice_totals(
        released, line_count=1, subtotal_cents=3075, discount_cents=0, total_cents=3075
    )

    assert fixtures.read_media_order(api, chain["order"]["id"])["status"] == "SUBMITTED"
    assert_election_axes(
        fixtures.read_election(api, chain["election"]["id"]), "PENDING", "ORDERED"
    )


def test_15_approving_reviewer_cannot_reopen_the_swipe_they_blessed(api):
    """PRD §3.7: "Reopening from `AUTO_SUBSTANTIATED` or from `SUBSTANTIATED` additionally
    requires the acting `X-User-ID` to differ from the transaction's recorded
    `approved_by_user_id`: the reviewer who blessed a swipe may not be the reviewer who
    reopens it."
    PRD §3.7: "On approval the claim moves `SUBMITTED → APPROVED` with
    `reviewed_by_user_id` recording the acting `X-User-ID`, and the underlying swipe moves
    `PENDING_DOCS → SUBSTANTIATED` with `approved_by_user_id` recording that same acting
    `X-User-ID`."

    Design: Corner/rbac/transaction_reopen_by_the_approving_reviewer_is_rejected
    """
    base = fixtures.make_submitted_claim(api)

    approved = validate_success(
        api.approve_substantiation_claim(
            base["claim"]["id"], make_compliance_reviewer_headers("rev-alpha")
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "rev-alpha"

    settled = fixtures.read_transaction(api, base["transaction"]["id"])
    assert settled["substantiation_status"] == "SUBSTANTIATED"
    assert settled["approved_by_user_id"] == "rev-alpha"
    assert settled["reopen_count"] == 0

    validate_error(
        api.reopen_card_transaction(
            base["transaction"]["id"],
            {"reason": "same reviewer attempts their own audit"},
            make_compliance_reviewer_headers("rev-alpha"),
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )

    after = fixtures.read_transaction(api, base["transaction"]["id"])
    assert after["substantiation_status"] == "SUBSTANTIATED"
    assert after["reopen_count"] == 0
    assert after["version"] == settled["version"]


def test_16_a_second_reviewer_reopens_the_substantiated_swipe(api):
    """PRD §3.7: "Reopening from `AUTO_SUBSTANTIATED` or from `SUBSTANTIATED` additionally
    requires the acting `X-User-ID` to differ from the transaction's recorded
    `approved_by_user_id`: the reviewer who blessed a swipe may not be the reviewer who
    reopens it."
    PRD §3.7: "Reopening from either of those two postures does nothing but set
    `substantiation_status` to `PENDING_DOCS`, increment `reopen_count` by 1 and advance
    `CardTransaction.version` by 1 — no money moves, because none had moved on approval."

    Design: Corner/rbac/transaction_reopen_by_the_approving_reviewer_is_rejected
    """
    base = fixtures.make_submitted_claim(api)
    validate_success(
        api.approve_substantiation_claim(
            base["claim"]["id"], make_compliance_reviewer_headers("rev-alpha")
        )
    )
    settled = fixtures.read_transaction(api, base["transaction"]["id"])

    reopened = validate_success(
        api.reopen_card_transaction(
            base["transaction"]["id"],
            {"reason": "an independent reviewer pulls the file for audit"},
            make_compliance_reviewer_headers("rev-beta"),
        )
    )
    assert reopened["substantiation_status"] == "PENDING_DOCS"
    assert reopened["reopen_count"] == 1
    assert reopened["version"] == settled["version"] + 1
    assert reopened["posted_spend_cents"] == 3000, "a reopen from SUBSTANTIATED moves no money"

    account = fixtures.read_account(api, base["account"]["id"])
    assert account["spent_cents"] == 3000
    assert account["available_balance_cents"] == 7000
    assert_account_conservation(account)
