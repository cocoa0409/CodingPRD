"""Loan origination: principal computation, required fields, state and role gates,
and the separation-of-duties / principal validation precedence."""
from test_helpers import (
    validate_success, validate_error,
    api_client,
    constants,
    factories as f,
    fixtures as fx,
    make_appraiser_headers, make_officer_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_initial_loan_state_is_active(api):
    """PRD §3.3: "Origination drives the pledged item from `APPRAISED` to `PLEDGED`
    and creates a `Loan` in `ACTIVE` status."
    PRD §3.3: "The loan's `periods_charged` begins at 0 (origination locks no finance
    period; the live period is computed on demand), its `renewal_count` begins at 0,
    and its `police_hold_flag` begins false."

    Design: Corner/state_machines/initial_loan_state_is_active
    """
    ctx = fx.setup_active_loan()
    loan = ctx["loan"]
    assert loan["status"] == "ACTIVE"
    assert loan["version"] == 1
    assert loan["periods_charged"] == 0
    assert loan["renewal_count"] == 0


def test_loan_amount_capped_to_state_max_principal(api):
    """PRD §3.3: "First the loan-to-value figure is computed: multiply the item's
    `appraised_value_cents` by the schedule's `loan_to_value_bps`, divide by 10000,
    and take the floor of the result to whole cents. The principal is then the smaller
    of that loan-to-value figure and the schedule's `max_principal_cents`."

    Design: Corner/entities/loan_amount_capped_to_state_max_principal
    """
    base = fx.setup_schedule_and_shop(schedule=constants.CA_SCHEDULE)
    customer = fx.create_customer()
    item = fx.create_appraised_item(base["shop"]["id"], customer["id"],
                                    appraised_value_cents=600000)
    loan = fx.originate_loan(base["shop"]["id"], item["id"], base["bin"]["id"])
    # LTV 300000 clamped to CA cap 250000.
    assert loan["principal_cents"] == 250000


def test_create_loan_missing_storage_bin_id_returns_invalid_request(api):
    """PRD §3.3: "Originating a loan is the exclusive work of a `LoanOfficer`, who
    supplies the `shop_id`, the `pawn_item_id` of the collateral, and the
    `storage_bin_id` of the bin chosen to hold it."
    PRD §2.11: "well-formedness of the request body — required fields present, enum
    values in range, integers non-negative where required (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_loan_missing_storage_bin_id_returns_invalid_request
    """
    base = fx.setup_schedule_and_shop()
    customer = fx.create_customer()
    item = fx.create_appraised_item(base["shop"]["id"], customer["id"])
    res = api.create_loan(
        {"shop_id": base["shop"]["id"], "pawn_item_id": item["id"]},
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_originate_unappraised_item_returns_item_not_appraised(api):
    """PRD §3.3: "Origination is only permitted when the item is in `APPRAISED` status;
    an attempt against an item that has not yet been appraised is rejected with
    `ERR_ITEM_NOT_APPRAISED`."

    Design: Corner/errors/originate_unappraised_item_returns_item_not_appraised
    """
    base = fx.setup_schedule_and_shop()
    customer = fx.create_customer()
    item = validate_success(api.create_item(
        f.create_item_payload(base["shop"]["id"], customer["id"]), OFFICER), 201)
    assert item["status"] == "INTAKE"
    res = api.create_loan(
        f.create_loan_payload(base["shop"]["id"], item["id"], base["bin"]["id"]),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_ITEM_NOT_APPRAISED", 409)


def test_appraiser_cannot_originate_loan_role_check(api):
    """PRD §3.3: "Originating a loan is the exclusive work of a `LoanOfficer`".
    PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/appraiser_cannot_originate_loan_role_check
    """
    base = fx.setup_schedule_and_shop()
    customer = fx.create_customer()
    item = fx.create_appraised_item(base["shop"]["id"], customer["id"])
    res = api.create_loan(
        f.create_loan_payload(base["shop"]["id"], item["id"], base["bin"]["id"]),
        make_appraiser_headers("appraiser-9"))
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)


def test_originate_for_flagged_customer_returns_flagged(api):
    """PRD §3.3: "the customer-flag check, where the named customer must not be flagged
    by law enforcement (`ERR_CUSTOMER_FLAGGED`)".
    PRD §3.10: "Placing a hold on a pawn item that is currently collateral on a live
    loan sets that loan's `police_hold_flag` to true, moves the loan to `POLICE_HELD`,
    and flags the borrowing customer's `is_flagged` to true — which is what later blocks
    new originations naming that customer."

    Design: Corner/errors/originate_for_flagged_customer_returns_flagged
    """
    base = fx.setup_schedule_and_shop(police_reporting_enabled=True)
    customer = fx.create_customer(full_name="Flagged Borrower")
    item1 = fx.create_appraised_item(base["shop"]["id"], customer["id"],
                                     description="Item1", serial_number="SN-A")
    fx.originate_loan(base["shop"]["id"], item1["id"], base["bin"]["id"])
    # A pawn-item hold flags the customer.
    fx.place_pawn_item_hold(item1["id"], case_number="CASE-FL")

    item2 = fx.create_appraised_item(base["shop"]["id"], customer["id"],
                                     description="Item2")
    res = api.create_loan(
        f.create_loan_payload(base["shop"]["id"], item2["id"], base["bin"]["id"]),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_CUSTOMER_FLAGGED", 409)


# ── Difficulty: segregation_of_duties (safety) outranks principal (fiscal) ──

def test_segregation_of_duties_blocks_appraiser_originating(api):
    """PRD §3.2: "The originating `LoanOfficer`'s `X-User-ID` must not equal the
    `appraised_by_user_id` of the pledged item; if the same user attempts to both
    appraise and lend, origination is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_safety_beats_principal_fiscal
    """
    base = fx.setup_schedule_and_shop()
    customer = fx.create_customer(full_name="Lou Borrower")
    # Same user "user-shared" appraises a low-value item.
    item = validate_success(api.create_item(
        f.create_item_payload(base["shop"]["id"], customer["id"],
                              description="Cheap trinket"), OFFICER), 201)
    validate_success(api.appraise_item(
        item["id"], f.appraise_item_payload(1),
        make_appraiser_headers("user-shared")), 200)
    res = api.create_loan(
        f.create_loan_payload(base["shop"]["id"], item["id"], base["bin"]["id"]),
        make_officer_headers("user-shared"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", 403)


def test_segregation_of_duties_outranks_principal_non_positive(api):
    """PRD §3.3: "Several further gates apply before the loan is created, evaluated in
    this order after existence, body well-formedness, and state are satisfied: the
    separation-of-duties check of §3.2 (`ERR_SEGREGATION_OF_DUTIES`); the police-hold
    check, where no `ACTIVE` police hold may name the collateral (`ERR_POLICE_HOLD_ACTIVE`);
    the customer-flag check, where the named customer must not be flagged by law
    enforcement (`ERR_CUSTOMER_FLAGGED`); the storage-bin capacity check described below
    (`ERR_BIN_CAPACITY_EXCEEDED`); and the positive-principal check
    (`ERR_PRINCIPAL_NON_POSITIVE`)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_safety_beats_principal_fiscal
    """
    base = fx.setup_schedule_and_shop()
    customer = fx.create_customer(full_name="Lou Borrower")
    # Appraise at 1c so the computed principal would be 0 (LTV floor(0.5)=0),
    # AND the appraiser is the same user who will originate (segregation breach).
    item = validate_success(api.create_item(
        f.create_item_payload(base["shop"]["id"], customer["id"],
                              description="Cheap trinket"), OFFICER), 201)
    validate_success(api.appraise_item(
        item["id"], f.appraise_item_payload(1),
        make_appraiser_headers("user-shared")), 200)
    res = api.create_loan(
        f.create_loan_payload(base["shop"]["id"], item["id"], base["bin"]["id"]),
        make_officer_headers("user-shared"))
    # Safety (segregation) outranks fiscal (principal-non-positive).
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", 403)


# ── Corner: FK reverse-reachability for Loan.pawn_item_id ──

def test_fk_reverse_loans_by_pawn_item_id(api):
    """PRD §4 (endpoint table): "List loans (filterable by `pawn_item_id`,
    `customer_id`, `storage_bin_id`, `shop_id`)".
    PRD §3.3: "the `pawn_item_id` of the collateral".

    Design: Corner/cross_cutting_complexity_layers/fk_reverse_loans_by_pawn_item_id
    """
    ctx = fx.setup_active_loan()
    res = api.list_loans(OFFICER, params={"pawn_item_id": ctx["item"]["id"]})
    body = res.json()
    data = body["data"]
    assert len([l for l in data if l["id"] == ctx["loan"]["id"]]) == 1
    match = next(l for l in data if l["id"] == ctx["loan"]["id"])
    assert match["pawn_item_id"] == ctx["item"]["id"]
