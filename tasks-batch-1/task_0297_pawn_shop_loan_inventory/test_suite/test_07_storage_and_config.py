"""Shop / schedule / storage configuration, intake & appraisal, the storage-bin
half-open capacity overlap, authentication, pagination, and FK reverse-reachability."""
from test_helpers import (
    validate_success, validate_error,
    constants,
    factories as f,
    fixtures as fx,
    make_appraiser_headers, make_officer_headers,
    build_user_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ── Difficulty: storage-bin half-open capacity overlap ──

def test_storage_bin_capacity_exceeded_on_overlapping_origination(api):
    """PRD §3.3: "The system considers every other loan assigned to the same bin that is
    not in a terminal state (those in `ACTIVE`, `IN_GRACE`, or `POLICE_HELD`) and counts
    how many of their half-open occupation intervals share any instant with the new loan's
    interval ... If that overlapping count plus the new loan would exceed the bin's
    `capacity`, origination is rejected with `ERR_BIN_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/storage_bin_capacity_halfopen_overlap
    """
    base = fx.setup_schedule_and_shop()  # sets clock to EPOCH
    shop_id = base["shop"]["id"]
    # A capacity-1 bin.
    tight_bin = validate_success(api.create_storage_bin(
        f.create_storage_bin_payload(shop_id, label="TIGHT", capacity=1), MANAGER), 201)
    customer = fx.create_customer(full_name="Rex Borrower")
    item_a = fx.create_appraised_item(shop_id, customer["id"], description="Item A")
    fx.originate_loan(shop_id, item_a["id"], tight_bin["id"])  # occupies [Jan1, Mar2)
    # A second overlapping origination into the same capacity-1 bin must be rejected.
    item_b = fx.create_appraised_item(shop_id, customer["id"], description="Item B")
    res = api.create_loan(
        f.create_loan_payload(shop_id, item_b["id"], tight_bin["id"]),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_BIN_CAPACITY_EXCEEDED", 409)


def test_storage_bin_within_capacity_origination_succeeds(api):
    """PRD §3.3: "The chosen bin must have room for the new collateral across the loan's
    occupation interval, which runs from `origination_at` up to but not including
    `grace_end_at` — a half-open interval."

    Design: Difficulty/resource_temporal_overlap/storage_bin_capacity_halfopen_overlap
    """
    base = fx.setup_schedule_and_shop()
    shop_id = base["shop"]["id"]
    bin2 = validate_success(api.create_storage_bin(
        f.create_storage_bin_payload(shop_id, label="ROOMY", capacity=2), MANAGER), 201)
    customer = fx.create_customer(full_name="Roomy Borrower")
    item_a = fx.create_appraised_item(shop_id, customer["id"], description="Item A")
    fx.originate_loan(shop_id, item_a["id"], bin2["id"])
    item_b = fx.create_appraised_item(shop_id, customer["id"], description="Item B")
    # Second concurrent loan fits within capacity 2.
    loan_b = fx.originate_loan(shop_id, item_b["id"], bin2["id"])
    assert loan_b["status"] == "ACTIVE"


# ── Corner: shop creation mints the drawer at 0 and defaults reporting true ──

def test_create_shop_mints_drawer_and_defaults(api):
    """PRD §3.1: "A shop carries a `name`, the `state_code` it operates in (again one of
    `FL`, `TX`, or `CA`), and a `police_reporting_enabled` flag that defaults to true."
    PRD §3.1: "Creating a shop also mints that shop's single cash drawer at a zero balance
    and records the convenience `cash_drawer_id` pointer; the drawer is reachable from the
    shop as an array of zero or one."

    Design: Corner/entities/create_shop_mints_drawer_and_defaults
    """
    shop = validate_success(api.create_shop(
        {"name": "Default Shop", "state_code": "TX"}, MANAGER), 201)
    assert shop["police_reporting_enabled"] is True
    drawers = api.get_shop_drawer(shop["id"], MANAGER).json()["data"]
    assert len(drawers) == 1
    assert drawers[0]["balance_cents"] == 0


# ── Corner: duplicate gov_id_number rejected ──

def test_duplicate_gov_id_rejected(api):
    """PRD §3.2: "The `gov_id_number` is unique; re-registering an already-known
    government ID is rejected with `ERR_DUPLICATE_GOV_ID`."

    Design: Corner/entities/duplicate_gov_id_rejected
    """
    gov = f.unique_gov_id("ID-DUP")
    validate_success(api.create_customer(
        f.create_customer_payload(full_name="First", gov_id_number=gov), OFFICER), 201)
    res = api.create_customer(
        f.create_customer_payload(full_name="Second", gov_id_number=gov), OFFICER)
    validate_error(res, "ERR_DUPLICATE_GOV_ID", 409)


# ── Corner: duplicate state schedule rejected ──

def test_duplicate_state_schedule_rejected(api):
    """PRD §3.1: "The `state_code` is unique across schedules; attempting to create a
    second schedule for a state that already has one is rejected with
    `ERR_DUPLICATE_SCHEDULE`."

    Design: Corner/entities/duplicate_state_schedule_rejected
    """
    validate_success(api.create_state_schedule(
        f.create_state_schedule_payload(**constants.CA_SCHEDULE), MANAGER), 201)
    dupe = dict(constants.CA_SCHEDULE)
    dupe["monthly_interest_bps"] = 300
    res = api.create_state_schedule(f.create_state_schedule_payload(**dupe), MANAGER)
    validate_error(res, "ERR_DUPLICATE_SCHEDULE", 409)


# ── Corner: appraise stamps appraised_by_user_id from X-User-ID ──

def test_appraise_sets_appraised_by_user_id_system_field(api):
    """PRD §3.2: "Appraising an item drives it from `INTAKE` to `APPRAISED`: the appraiser
    supplies an `appraised_value_cents`, which must be greater than zero, and the system
    records that value plus the appraiser's identity in `appraised_by_user_id` (taken from
    `X-User-ID`)."

    Design: Corner/entities/appraise_sets_appraised_by_user_id_system_field
    """
    shop = validate_success(api.create_shop(
        f.create_shop_payload(name="FL Branch", state_code="FL"), MANAGER), 201)
    customer = fx.create_customer(full_name="W Borrower")
    item = validate_success(api.create_item(
        f.create_item_payload(shop["id"], customer["id"], description="Ring"), OFFICER), 201)
    appraised = validate_success(api.appraise_item(
        item["id"], f.appraise_item_payload(12345),
        make_appraiser_headers("appraiser-77")), 200)
    assert appraised["status"] == "APPRAISED"
    assert appraised["appraised_value_cents"] == 12345
    assert appraised["appraised_by_user_id"] == "appraiser-77"


# ── Corner: GET a nonexistent loan returns NOT_FOUND ──

def test_get_loan_nonexistent_returns_not_found(api):
    """PRD §2.5: "the request is rejected with `ERR_NOT_FOUND` against the **first** path
    identifier that does not resolve to an existing resource".

    Design: Corner/entities/get_loan_nonexistent_returns_not_found
    """
    res = api.get_loan("00000000-0000-4000-8000-000000000000", OFFICER)
    validate_error(res, "ERR_NOT_FOUND", 404)


# ── Corner: missing/unknown role header returns UNAUTHENTICATED ──

def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` that is
    not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    validate_success(api.create_shop(
        f.create_shop_payload(name="FL Branch", state_code="FL"), MANAGER), 201)
    bad_headers = build_user_headers("nobody-1", "Nobody")
    res = api.create_customer(
        f.create_customer_payload(full_name="NoAuth"), bad_headers)
    validate_error(res, "ERR_UNAUTHENTICATED", 401)


# ── Corner: out-of-range pagination limit rejected ──

def test_pagination_limit_out_of_range_returns_error(api):
    """PRD §2.3: "The `limit` parameter caps how many items are returned; it defaults to
    10, may be no smaller than 1, and may be no larger than 100 ... A `limit` or `offset`
    outside its allowed range is rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/errors/pagination_limit_out_of_range_returns_error
    """
    res = api.list_state_schedules(MANAGER, params={"limit": 500})
    validate_error(res, "ERR_VALIDATION_PAGINATION", 422)


# ── Corner: FK reverse-reachability for Loan.storage_bin_id ──

def test_fk_reverse_storage_bin_loans(api):
    """PRD §4 (endpoint table): "Loans occupying this bin".
    PRD §3.3: "the `storage_bin_id` of the bin chosen to hold it".

    Design: Corner/cross_cutting_complexity_layers/fk_reverse_storage_bin_loans
    """
    ctx = fx.setup_active_loan()
    data = api.list_storage_bin_loans(ctx["bin"]["id"], MANAGER).json()["data"]
    matches = [l for l in data if l["id"] == ctx["loan"]["id"]]
    assert len(matches) == 1
    assert matches[0]["storage_bin_id"] == ctx["bin"]["id"]
