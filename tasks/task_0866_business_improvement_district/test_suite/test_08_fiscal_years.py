"""Fiscal-year interval overlap vs adjacency, and the ACTIVE-district precondition on adopt."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, new_bid, add_parcel, new_fiscal_year, new_budget, add_line, propose,
    create_fiscal_year_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]
BOARD = TEST_USERS["board_member_headers"]


def test_overlapping_fiscal_year_rejected(api):
    """PRD §3.2: "a new fiscal year may not overlap any existing fiscal year of the same
    district, though exact adjacency — where one year's end equals the next year's start —
    is permitted. An overlapping interval is rejected with ERR_FISCAL_YEAR_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/fiscal_year_halfopen_overlap_vs_adjacency
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="FY BID")
    new_fiscal_year(bid["id"])  # FY2028 [2027-07-01, 2028-07-01)
    resp = api.create_fiscal_year(bid["id"], create_fiscal_year_payload(
        year_label="OVERLAP", start_date="2028-01-01T00:00:00Z",
        end_date="2028-12-31T00:00:00Z", assessment_due_date="2028-02-01T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_FISCAL_YEAR_OVERLAP.value)


def test_adjacent_fiscal_year_accepted(api):
    """PRD §3.2: "exact adjacency — where one year's end equals the next year's start — is
    permitted."

    Design: Difficulty/resource_temporal_overlap/fiscal_year_halfopen_overlap_vs_adjacency
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="FY BID")
    new_fiscal_year(bid["id"])  # FY2028 [2027-07-01, 2028-07-01)
    created = validate_success(api.create_fiscal_year(bid["id"], create_fiscal_year_payload(
        year_label="FY2029", start_date="2028-07-01T00:00:00Z",
        end_date="2029-07-01T00:00:00Z", assessment_due_date="2028-08-01T00:00:00Z"), ADMIN), 201)
    assert created["start_date"].startswith("2028-07-01")


def _forming_bid_with_proposed_budget(api):
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="CE1 BID")  # never activated -> FORMING
    add_parcel(bid["id"], apn="PX-1")
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=4025000, other_revenue_cents=0)
    add_line(budget["id"], "CLEAN", 4025000)
    propose(budget["id"])
    return budget


def test_adopt_on_forming_district_rejected(api):
    """PRD §3.3: "Adoption requires that the owning district be ACTIVE — otherwise
    ERR_BID_NOT_ACTIVE — and that the budget be PROPOSED."

    Design: Difficulty/cross_entity_state_dependency/adopt_requires_bid_active
    """
    budget = _forming_bid_with_proposed_budget(api)
    resp = api.adopt_budget(budget["id"], BOARD)
    validate_error(resp, ApiErrorId.ERR_BID_NOT_ACTIVE.value)


def test_budget_stays_proposed_after_rejected_adopt(api):
    """PRD §3.3: "Adoption requires that the owning district be ACTIVE — otherwise
    ERR_BID_NOT_ACTIVE — and that the budget be PROPOSED."

    Design: Difficulty/cross_entity_state_dependency/adopt_requires_bid_active
    """
    budget = _forming_bid_with_proposed_budget(api)
    api.adopt_budget(budget["id"], BOARD)
    got = validate_success(api.get_budget(budget["id"], ADMIN))
    assert got["status"] == "PROPOSED"
