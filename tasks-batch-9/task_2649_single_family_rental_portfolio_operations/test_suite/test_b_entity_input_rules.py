"""The two cheapest ladder rungs and the filter-before-count rule for listings.

Ranks 10 and 12 both answer `ERR_INVALID_REQUEST` at 400 and both run before every existence
and business check, so a malformed payload never reaches the row it names -- which is also why
the listing counts at the end of each test must not have moved.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_SLOT_DURATION_INVALID
from test_helpers.assertions import assert_page_meta, failed, page
from test_helpers.constants import CLOCK_AUG_01


def test_home_listing_filters_before_it_counts_and_pages(api):
    """Three ATL homes and one DAL home: the ATL filter counts 3, the unfiltered read 4.

    PRD SS2.3: "`limit` defaults to 10 when omitted ... `offset` defaults to 0 and counts rows
    to skip from the beginning of the ordered result set. ... The four pagination fields
    reported in `meta` are `limit` (the effective page size actually applied), `offset` (the
    effective offset actually applied), `total_count` (the number of rows matching the filters
    before pagination) and `has_more` (true when rows remain beyond this page). Filter query
    parameters, where an endpoint offers them, narrow the matched set before `total_count` is
    computed."  PRD SS3.1: the home register "is readable one home at a time and as a list
    filterable by `market_id`".

    Design: Corner/entities/home_listing_filters_by_market_and_paginates
    """
    x.set_clock(api, CLOCK_AUG_01)
    atl = x.create_market(api)
    dal = x.create_market(api, f.dallas_market_payload_strict())
    atl_ids = {
        x.create_home(api, atl["id"])["id"],
        x.create_home(api, atl["id"], f.home_payload_no_hoa(atl["id"]))["id"],
        x.create_home(api, atl["id"], f.home_payload_second(atl["id"]))["id"],
    }
    dal_id = x.create_home(api, dal["id"], f.home_payload_dallas(dal["id"]))["id"]

    first_rows, first_meta = page(
        api.list_homes(x.ADMIN, {"market_id": atl["id"], "limit": 2, "offset": 0})
    )
    assert_page_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)
    assert len(first_rows) == 2
    first_page_ids = {row["id"] for row in first_rows}
    assert first_page_ids <= atl_ids
    assert dal_id not in first_page_ids

    second_rows, second_meta = page(
        api.list_homes(x.ADMIN, {"market_id": atl["id"], "limit": 2, "offset": 2})
    )
    assert_page_meta(second_meta, total_count=3, has_more=False)
    assert len(second_rows) == 1
    assert {row["id"] for row in second_rows} == atl_ids - first_page_ids

    all_rows, all_meta = page(api.list_homes(x.ADMIN, {"limit": 10, "offset": 0}))
    assert_page_meta(all_meta, total_count=4, has_more=False)
    assert {row["id"] for row in all_rows} == atl_ids | {dal_id}


def test_an_absent_field_and_a_degenerate_window_are_both_rank_ten_failures(api):
    """A work order without crew_size and a zero-length window are refused at 400.

    PRD SS2.7: "**Rank 10 -- malformed payload.** A required input field is absent ... Reported
    as `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."  PRD SS2.7: "**Rank 12 --
    inverted or degenerate interval.** A work-order window whose `scheduled_start_date` is
    later than its `scheduled_end_date`; a showing window whose `starts_at` is at or after its
    `ends_at` ... Reported as `ERR_INVALID_REQUEST` (400)."  Rank 12 sits far below the
    duration rule, which is "**Rank 450 -- showing window too short.**
    `ERR_SLOT_DURATION_INVALID` (422) on showing-slot creation", and "**Evaluation stops at the
    first violated rule, and only that rule's error is reported.**"  PRD SS3.3 makes
    `crew_size` a required input: it "is the number of crew members required on each scheduled
    date and is at least 1."

    Design: Corner/entities/missing_required_fields_returns_invalid_request
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])

    # The design index also expects a home payload without ``asking_rent_cents`` to be a rank
    # 10 failure, but PRD SS3.1 declares that field optional -- it "may be omitted and then
    # defaults to the market's `rent_index_cents`" -- so that call is not translated here.
    failed(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                crew_size=None,
                scheduled_end_date="2026-08-11",
            ),
            x.OPS,
        ),
        ERR_INVALID_REQUEST,
    )

    body = failed(
        api.create_showing_slot(
            f.showing_slot_payload(
                home["id"],
                starts_at="2026-08-20T15:00:00Z",
                ends_at="2026-08-20T15:00:00Z",
            ),
            x.AGENT,
        ),
        ERR_INVALID_REQUEST,
    )
    assert body.get("error_id") != ERR_SLOT_DURATION_INVALID

    _rows, meta = page(api.list_homes(x.ADMIN, {"market_id": market["id"]}))
    assert_page_meta(meta, total_count=1)
    _slots, slot_meta = page(api.list_showing_slots(x.AGENT, {"home_id": home["id"]}))
    assert_page_meta(slot_meta, total_count=0)


def test_off_range_off_enum_and_negative_money_are_all_rank_ten_failures(api):
    """A 3001 millage, a credit tier E, a DRONE access mode and a -1 rent all give 400.

    PRD SS2.7: "**Rank 10 -- malformed payload.** A required input field is absent; an input
    field has the wrong JSON type; an enum-typed field carries a value outside its declared
    set; a money or count field is negative; a basis-point field falls outside the inclusive
    range 0 through 1,000,000; a field violates the numeric range declared for it in this
    document ... Reported as `ERR_INVALID_REQUEST` (400)."  The ranges and sets those calls
    break are declared in PRD SS2.10 -- "`millage_bps` is the annual property-tax rate in basis
    points of a home's assessed value and must fall between 1 and 3000 inclusive" -- in PRD
    SS3.6 -- "a `credit_tier` of `A`, `B`, `C` or `D`" -- and in PRD SS3.7, where `access_mode`
    is "one of `SMART_LOCK`, `LOCKBOX` or `AGENT_ESCORT`".

    Design: Corner/entities/off_enum_and_out_of_range_values_returns_invalid_request
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])

    failed(
        api.create_market(f.dallas_market_payload_strict(millage_bps=3001), x.ADMIN),
        ERR_INVALID_REQUEST,
    )
    failed(
        api.create_prospect(
            f.prospect_payload(
                market["id"],
                email="p9@example.com",
                full_name="Pat Nine",
                phone="+1-404-555-0109",
                declared_monthly_income_cents=500000,
                credit_tier="E",
            ),
            x.ANON,
        ),
        ERR_INVALID_REQUEST,
    )
    failed(
        api.create_showing_slot(
            f.showing_slot_payload(home["id"], access_mode="DRONE"), x.AGENT
        ),
        ERR_INVALID_REQUEST,
    )
    failed(
        api.create_home(
            f.home_payload(
                market["id"], address_line1="551 Glenwood Ave", asking_rent_cents=-1
            ),
            x.ANALYST,
        ),
        ERR_INVALID_REQUEST,
    )

    _markets, market_meta = page(api.list_markets(x.ADMIN))
    assert_page_meta(market_meta, total_count=1)
    _homes, home_meta = page(api.list_homes(x.ADMIN))
    assert_page_meta(home_meta, total_count=1)
    _prospects, prospect_meta = page(api.list_prospects(x.AGENT))
    assert_page_meta(prospect_meta, total_count=0)
