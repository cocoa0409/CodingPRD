"""District creation, parcel enrollment, weighting, and lifecycle basics."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_bid_payload, create_parcel_payload,
    assert_bid, assert_parcel,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]
BOARD = TEST_USERS["board_member_headers"]


def test_create_district_returns_forming_version_one_and_defaults(api):
    """PRD §3.1: "A new district begins life in FORMING status."
    PRD §2.4: "an integer version that begins at 1 on creation and increments by one
    on every persisted mutation of that resource."
    PRD §3.1: "when omitted these default to 50000 cents and 10000000 cents respectively."

    Design: Corner/entities/bid_create_returns_system_fields
    """
    created = validate_success(api.create_bid(create_bid_payload(name="New BID"), ADMIN), 201)
    assert_bid(created)
    got = validate_success(api.get_bid(created["id"], ADMIN))
    assert got["status"] == "FORMING", f"expected FORMING, got {got['status']}"
    assert got["version"] == 1, f"expected version 1, got {got['version']}"
    assert got["min_assessment_cents"] == 50000
    assert got["max_assessment_cents"] == 10000000


def test_get_missing_district_returns_not_found(api):
    """PRD §2.4: "a missing district yields ERR_BID_NOT_FOUND".

    Design: Corner/entities/bid_not_found_returns_404
    """
    resp = api.get_bid(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BID_NOT_FOUND.value)


def test_create_parcel_without_use_class_rejected(api):
    """PRD §2.6: "required fields present, enums and types valid, and amounts strictly
    positive where required, else ERR_VALIDATION."

    Design: Corner/entities/parcel_missing_use_class_rejected
    """
    bid = get_success_data(api.create_bid(create_bid_payload(name="V BID"), ADMIN))
    payload = create_parcel_payload()
    payload.pop("use_class")
    resp = api.create_parcel(bid["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_exempt_parcel_has_zero_weighted_base(api):
    """PRD §3.1: "The exempt flag is true exactly when use_class is RESIDENTIAL_EXEMPT or
    NONPROFIT_EXEMPT; exempt parcels are excluded from the rate denominator and always
    receive a zero assessment." PRD §3.1: "for an exempt parcel it is zero".

    Design: Corner/entities/exempt_parcel_weighted_base_zero
    """
    bid = get_success_data(api.create_bid(create_bid_payload(name="Ex BID"), ADMIN))
    parcel = validate_success(api.create_parcel(bid["id"], create_parcel_payload(
        apn="NP-1", owner_name="Charity", use_class="NONPROFIT_EXEMPT",
        assessed_value_cents=100000000, linear_frontage_ft=50, building_sqft=10000), ADMIN), 201)
    assert_parcel(parcel)
    assert parcel["exempt"] is True
    assert parcel["weighted_base"] == 0


def test_commercial_parcel_weighted_base_computed(api):
    """PRD §3.1: "the system first forms a base-points figure by adding three terms — the
    value weight assessment_weight_value multiplied by the assessed value expressed in
    whole dollars (that is, assessed_value_cents divided by 100), plus the frontage weight
    assessment_weight_frontage multiplied by linear_frontage_ft, plus the square-foot
    weight assessment_weight_sqft multiplied by building_sqft — and then multiplies that
    base-points figure by the use-class multiplier for the parcel's class."
    PRD §3.1: "1.00 for COMMERCIAL".

    Design: Corner/entities/commercial_parcel_weighted_base_computed
    """
    bid = get_success_data(api.create_bid(create_bid_payload(
        name="WB BID", assessment_weight_value=0.0005,
        assessment_weight_frontage=2.0, assessment_weight_sqft=0.01), ADMIN))
    parcel = validate_success(api.create_parcel(bid["id"], create_parcel_payload(
        apn="WB-1", use_class="COMMERCIAL",
        assessed_value_cents=100000000, linear_frontage_ft=50, building_sqft=10000), ADMIN), 201)
    # 0.0005*(100000000/100) + 2.0*50 + 0.01*10000 = 500 + 100 + 100 = 700, x1.00
    assert parcel["weighted_base"] == 700


def test_new_district_initial_state_is_forming(api):
    """PRD §3.1: "A new district begins life in FORMING status."

    Design: Corner/state_machines/new_bid_initial_state_forming
    """
    created = get_success_data(api.create_bid(create_bid_payload(name="Init BID"), ADMIN))
    got = validate_success(api.get_bid(created["id"], ADMIN))
    assert got["status"] == "FORMING"


def test_activate_already_active_district_rejected(api):
    """PRD §2.6: "the target resource is in a state from which the requested transition is
    defined, else ERR_INVALID_STATE".
    PRD §3.1: "A BoardMember activates a forming district, transitioning it FORMING → ACTIVE."

    Design: Corner/state_machines/activate_already_active_rejected
    """
    bid = get_success_data(api.create_bid(create_bid_payload(name="AA BID"), ADMIN))
    get_success_data(api.create_parcel(bid["id"], create_parcel_payload(apn="AA-1"), ADMIN))
    get_success_data(api.activate_bid(bid["id"], BOARD))
    resp = api.activate_bid(bid["id"], BOARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_withdraw_already_withdrawn_parcel_rejected(api):
    """PRD §3.1: "A parcel may be withdrawn from the district by the administrator,
    transitioning it ACTIVE → WITHDRAWN."
    PRD §2.6: "the target resource is in a state from which the requested transition is
    defined, else ERR_INVALID_STATE".

    Design: Corner/state_machines/rewithdraw_parcel_rejected
    """
    bid = get_success_data(api.create_bid(create_bid_payload(name="WD BID"), ADMIN))
    parcel = get_success_data(api.create_parcel(bid["id"], create_parcel_payload(apn="WD-1"), ADMIN))
    get_success_data(api.withdraw_parcel(parcel["id"], ADMIN))
    resp = api.withdraw_parcel(parcel["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
