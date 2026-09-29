"""Every consequence of a write has settled by the time its response is read."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import assert_fields, assert_null_fields, assert_page, assert_score


def test_a_production_report_settles_the_wells_aggregates_in_one_read(api):
    """The next read needs no second call to see the write's consequences.

    The report answers with its own unrounded barrel-of-oil-equivalent figure while the well
    already carries the rounded aggregate, the recomputed idle count and the advanced last
    month; the refused duplicate month leaves all three exactly where they were, and the
    access request settles the well's other dimension just as immediately.

    PRD: "those consequences are **immediate and synchronous**: by the time a 2xx response is
    returned, every derived value and every dependent state has already settled. There is no
    deferred recomputation and no eventual consistency anywhere in this API." ... "The row's
    barrel-of-oil-equivalent figure `boe` is derived as the oil volume plus the gas volume
    divided by six, and it is deliberately stored **unrounded** at the row level; the
    two-decimal rounding happens exactly once, later, on the well's aggregate." ... "A month
    may be reported only once per well; a second attempt for the same well and the same month
    is rejected with `ERR_DUPLICATE_PRODUCTION_MONTH` (HTTP 409)."

    Design: Corner/consistency_model/every_write_is_visible_to_the_very_next_read_with_no_lag
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    well = fx.make_well(api, operator["id"], api_well_number="49-001-28001")
    assert_fields(well, idle_months=999, status="PRODUCING")
    assert_null_fields(well, "last_production_month")
    assert_score(well["cumulative_boe_60mo"], 0.00, "cumulative_boe_60mo at creation")
    assert_score(well["screening_score"], 59.90, "screening_score at creation")
    assert_score(well["remediation_score"], 81.00, "remediation_score at creation")

    record = validate_success(
        api.create_production_record(
            well["id"],
            f.production_payload("2026-07", oil_bbl=10.0, gas_mcf=3.0),
            users.INSPECTOR,
        ),
        201,
    )
    assert_fields(record, month="2026-07", well_id=well["id"])
    assert_score(record["boe"], 10.5, "row boe")

    settled = fx.read_well(api, well["id"])
    assert_fields(settled, last_production_month="2026-07", idle_months=1)
    assert_score(settled["cumulative_boe_60mo"], 10.50, "cumulative_boe_60mo")
    assert_score(settled["screening_score"], 59.90, "screening_score after production")
    assert_score(settled["remediation_score"], 81.00, "remediation_score after production")

    validate_error(
        api.create_production_record(
            well["id"],
            f.production_payload("2026-07", oil_bbl=99.0, gas_mcf=0),
            users.INSPECTOR,
        ),
        e.ERR_DUPLICATE_PRODUCTION_MONTH,
        409,
    )
    after_refusal = fx.read_well(api, well["id"])
    assert_fields(after_refusal, last_production_month="2026-07", idle_months=1)
    assert_score(after_refusal["cumulative_boe_60mo"], 10.50, "cumulative_boe_60mo held")
    assert_page(
        api.list_production_records(well["id"], users.INSPECTOR), 1, expected_total=1
    )

    access = fx.open_site_access(api, well["id"], mode="AGREEMENT")
    assert_fields(access, status="REQUESTED", well_id=well["id"])
    mirrored = fx.read_well(api, well["id"])
    assert_fields(mirrored, access_status="ACCESS_PENDING", status="PRODUCING")
    assert_score(mirrored["cumulative_boe_60mo"], 10.50, "cumulative_boe_60mo unmoved")
