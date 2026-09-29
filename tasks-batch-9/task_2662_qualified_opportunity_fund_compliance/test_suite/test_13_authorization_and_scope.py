"""Role authorization, investor ownership scope and fund-manager ownership."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fund_aggregates,
    assert_money,
    assert_percent,
)
from test_helpers.factories import (
    OMIT,
    create_asset_test_payload,
    create_eligible_gain_payload,
    create_fund_asset_payload,
    create_investor_payload,
    dispose_fund_asset_payload,
    self_certify_payload,
    set_clock_payload,
)
from test_helpers.fixtures import (
    list_fund_asset_tests,
    make_asset_test,
    make_eligible_gain,
    make_fund,
    make_fund_asset,
    make_investor,
    make_self_certified_fund,
    measure_asset_test,
    read_asset_test,
    read_fund,
    read_fund_asset,
    read_investor_statement,
    self_certify_fund,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CERTIFIER_HEADERS,
    FUND_MANAGER_USER_ID,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
    OFFICER_CERTIFIER_USER_ID,
    OFFICER_MEASURER_USER_ID,
    OTHER_FUND_MANAGER_USER_ID,
    OTHER_MANAGER_HEADERS,
    make_investor_headers,
)

UNKNOWN_INVESTOR_ID = "00000000-0000-4000-8000-000000000099"


def test_only_a_compliance_officer_may_certify_an_asset_test(api):
    """
    "A syntactically valid role that is simply not authorized for the endpoint being
    called is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    "A `FundManager` may measure a test and may never certify one."
    "The caller's role is authorized for the endpoint — `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/rbac/asset_test_certify_is_compliance_officer_exclusive
    """
    fund = make_self_certified_fund(
        api, name="Certify Authority QOF", entity_type="CORPORATION"
    )
    make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=500000.00,
        afs_fair_value=500000.00,
        original_use_in_zone=OMIT,
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-06-30T00:00:00Z",
    )
    measured = measure_asset_test(api, test["id"], MANAGER_HEADERS)
    assert measured["status"] == "MEASURED"
    assert measured["measured_by_user_id"] == FUND_MANAGER_USER_ID
    assert measured["result"] == "FAIL"

    refused = (
        MANAGER_HEADERS,
        ADMIN_HEADERS,
        make_investor_headers(UNKNOWN_INVESTOR_ID),
    )
    for headers in refused:
        validate_error(
            api.certify_asset_test(test["id"], None, headers),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

    still_measured = read_asset_test(api, test["id"])
    assert still_measured["status"] == "MEASURED"
    assert not still_measured["certified_by_user_id"]

    certified = validate_success(
        api.certify_asset_test(test["id"], None, CERTIFIER_HEADERS)
    )
    assert certified["status"] == "CERTIFIED_FAIL"
    assert certified["certified_by_user_id"] == OFFICER_CERTIFIER_USER_ID


def test_no_role_inherits_another_roles_exclusive_operations(api):
    """
    "A syntactically valid role that is simply not authorized for the endpoint being
    called is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    "The platform administrator owns investor onboarding, the attestation switch, the
    logical clock and the batch sweep, and may stand in for an investor or a manager on
    creation endpoints."
    "Any caller may read the clock, which returns the current `current_utc`."

    Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
    """
    fund = make_fund(api, name="Role Lattice QOF", entity_type="PARTNERSHIP")
    certified = self_certify_fund(api, fund["id"])
    assert certified["certification_status"] == "SELF_CERTIFIED"
    asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=250000.00,
        afs_fair_value=250000.00,
        original_use_in_zone=OMIT,
    )

    validate_error(
        api.self_certify_fund(
            fund["id"], self_certify_payload("2026-02-01T00:00:00Z"), ADMIN_HEADERS
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.create_investor(
            create_investor_payload(legal_name="Manager Minted Investor"),
            MANAGER_HEADERS,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        403,
    )
    rows, meta = validate_paginated(api.list_investors(ADMIN_HEADERS, {"limit": 100}))
    assert rows == []
    assert meta["total_count"] == 0

    validate_error(
        api.set_clock(set_clock_payload("2027-01-01T00:00:00Z"), MANAGER_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.dispose_fund_asset(
            asset["id"], dispose_fund_asset_payload(260000.00), CERTIFIER_HEADERS
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        403,
    )
    assert read_fund_asset(api, asset["id"])["status"] == "HELD"

    validate_error(
        api.create_fund_asset(
            create_fund_asset_payload(
                fund["id"],
                asset_class="CASH",
                acquisition_date="2026-01-06T00:00:00Z",
                unadjusted_cost_basis=10000.00,
                afs_fair_value=10000.00,
                original_use_in_zone=OMIT,
            ),
            make_investor_headers(UNKNOWN_INVESTOR_ID),
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        403,
    )
    assert_fund_aggregates(read_fund(api, fund["id"]), aggregate_asset_basis=250000.00)

    clock = validate_success(api.get_clock(MANAGER_HEADERS))
    assert clock["current_utc"].startswith("2026-08-01T00:00:00")


def test_one_investor_cannot_read_or_write_a_peers_records(api):
    """
    "Ownership checks on any resource that references an investor compare the resource's
    investor reference to `X-User-ID`: an eligible gain's `investor_id`, a deferral
    election's `investor_id`, and the investor identifier in the path of the
    single-investor read and statement endpoints. A mismatch is rejected with
    `ERR_INVESTOR_SCOPE_VIOLATION` (HTTP 403)."
    "This guards gain intake, the single-gain read, election create, election revoke,
    inclusion-event recording, step-up filing, the single-investor read and the investor
    statement read."
    "It is readable by the investor itself, by a `ComplianceOfficer` and by a
    `PlatformAdmin`, with the investor's own reads subject to the ownership scope of
    §2.1."

    Design: Corner/rbac/investor_cannot_reach_another_investors_records
    """
    peer_one = make_investor(
        api,
        legal_name="Peer One Trust",
        taxpayer_type="TRUST",
        tax_year_end_month=12,
        compliance_attestation_status="ATTESTED",
    )
    peer_two = make_investor(
        api,
        legal_name="Peer Two LLC",
        taxpayer_type="PARTNERSHIP",
        tax_year_end_month=12,
        compliance_attestation_status="ATTESTED",
    )
    assert peer_one["compliance_attestation_status"] == "ATTESTED"
    assert peer_two["compliance_attestation_status"] == "ATTESTED"
    gain = make_eligible_gain(
        api,
        peer_one["id"],
        eligible_amount=80000.00,
        realization_date="2026-07-01T00:00:00Z",
    )

    intruder = make_investor_headers(peer_two["id"])
    validate_error(
        api.get_eligible_gain(gain["id"], intruder),
        ApiErrorId.INVESTOR_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api.get_investor(peer_one["id"], intruder),
        ApiErrorId.INVESTOR_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api.get_investor_statement(peer_one["id"], intruder),
        ApiErrorId.INVESTOR_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api.create_eligible_gain(
            create_eligible_gain_payload(
                peer_one["id"],
                eligible_amount=5000.00,
                realization_date="2026-07-02T00:00:00Z",
            ),
            intruder,
        ),
        ApiErrorId.INVESTOR_SCOPE_VIOLATION.value,
        403,
    )
    rows, meta = validate_paginated(
        api.list_eligible_gains(
            ADMIN_HEADERS, {"limit": 100, "investor_id": peer_one["id"]}
        )
    )
    assert [row["id"] for row in rows] == [gain["id"]]
    assert meta["total_count"] == 1

    owned = validate_success(
        api.get_eligible_gain(gain["id"], make_investor_headers(peer_one["id"]))
    )
    assert_money(owned["eligible_amount"], 80000.00, "EligibleGain.eligible_amount")
    officer_view = read_investor_statement(api, peer_one["id"], MEASURER_HEADERS)
    assert_money(
        officer_view["eligible_gain_total"], 80000.00, "statement.eligible_gain_total"
    )


def test_a_peer_manager_is_locked_out_of_a_fund_it_does_not_own(api):
    """
    "It is compared against the `manager_user_id` recorded on the fund that owns the
    target resource; a mismatch is rejected with `ERR_FUND_MANAGER_MISMATCH` (HTTP 403)."
    "Fund-manager ownership — `ERR_FUND_MANAGER_MISMATCH` (403). This guards
    self-certification, asset record, asset disposal, asset-test creation, business
    registration, project creation, project expenditure, plan filing, plan activation,
    plan expenditure and cure request."
    "Requests are validated in a fixed order, and the **first** check that fails
    determines the response."

    Design: Corner/rbac/fund_manager_cannot_write_another_managers_fund
    """
    fund_one = make_fund(
        api,
        name="Manager One QOF",
        entity_type="PARTNERSHIP",
        manager_user_id=FUND_MANAGER_USER_ID,
    )
    self_certify_fund(api, fund_one["id"])
    fund_two = make_fund(
        api,
        name="Manager Two QOF",
        entity_type="CORPORATION",
        manager_user_id=OTHER_FUND_MANAGER_USER_ID,
    )

    def asset_payload():
        return create_fund_asset_payload(
            fund_one["id"],
            asset_class="CASH",
            acquisition_date="2026-01-05T00:00:00Z",
            unadjusted_cost_basis=300000.00,
            afs_fair_value=300000.00,
            original_use_in_zone=OMIT,
        )

    validate_error(
        api.create_fund_asset(asset_payload(), OTHER_MANAGER_HEADERS),
        ApiErrorId.FUND_MANAGER_MISMATCH.value,
        403,
    )
    assert_fund_aggregates(read_fund(api, fund_one["id"]), aggregate_asset_basis=0.00)

    validate_error(
        api.self_certify_fund(
            fund_one["id"],
            self_certify_payload("2026-02-01T00:00:00Z"),
            OTHER_MANAGER_HEADERS,
        ),
        ApiErrorId.FUND_MANAGER_MISMATCH.value,
        403,
    )
    validate_error(
        api.create_asset_test(
            fund_one["id"],
            create_asset_test_payload(
                measurement_date="2026-06-30T00:00:00Z",
                period_start="2026-01-01T00:00:00Z",
                period_end="2026-06-30T00:00:00Z",
            ),
            OTHER_MANAGER_HEADERS,
        ),
        ApiErrorId.FUND_MANAGER_MISMATCH.value,
        403,
    )
    assert list_fund_asset_tests(api, fund_one["id"]) == []

    recorded = validate_success(
        api.create_fund_asset(asset_payload(), MANAGER_HEADERS), 201
    )
    assert recorded["status"] == "HELD"
    assert_fund_aggregates(
        read_fund(api, fund_one["id"]), aggregate_asset_basis=300000.00
    )
    assert read_fund(api, fund_two["id"])["certification_status"] == "DRAFT"


def test_measurement_is_shared_by_the_manager_and_the_officer(api):
    """
    "Asset tests are opened per testing period by a `FundManager` who owns the fund or by
    a `ComplianceOfficer`."
    "Measuring a test moves it `DRAFT → MEASURED`, requires the owning fund to be
    `SELF_CERTIFIED`, records the caller's handle as `measured_by_user_id`, and sets the
    fund's `last_test_measurement_date` to this test's `measurement_date`."
    "This is why both roles that may measure (`FundManager` and `ComplianceOfficer`) are
    recorded on the test"

    Design: Corner/rbac/asset_test_measure_is_shared_by_manager_and_officer
    """
    fund = make_self_certified_fund(
        api, name="Shared Measure QOF", entity_type="CORPORATION"
    )
    make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=400000.00,
        afs_fair_value=400000.00,
        original_use_in_zone=OMIT,
    )
    opened_by_manager = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-03-31T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
    )
    opened_by_officer = validate_success(
        api.create_asset_test(
            fund["id"],
            create_asset_test_payload(
                measurement_date="2026-06-30T00:00:00Z",
                period_start="2026-04-01T00:00:00Z",
                period_end="2026-07-01T00:00:00Z",
            ),
            MEASURER_HEADERS,
        ),
        201,
    )

    measured_by_manager = measure_asset_test(
        api, opened_by_manager["id"], MANAGER_HEADERS
    )
    measured_by_officer = measure_asset_test(
        api, opened_by_officer["id"], MEASURER_HEADERS
    )

    assert measured_by_manager["status"] == "MEASURED"
    assert measured_by_manager["measured_by_user_id"] == FUND_MANAGER_USER_ID
    assert measured_by_manager["result"] == "FAIL"
    assert_percent(measured_by_manager["ratio_pct"], 0.0000, "AssetTest.ratio_pct")
    assert measured_by_officer["status"] == "MEASURED"
    assert measured_by_officer["measured_by_user_id"] == OFFICER_MEASURER_USER_ID
    assert measured_by_officer["result"] == "FAIL"
    assert not measured_by_manager["certified_by_user_id"]
    assert not measured_by_officer["certified_by_user_id"]

    rows, meta = validate_paginated(
        api.list_fund_asset_tests(fund["id"], MEASURER_HEADERS, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert {row["status"] for row in rows} == {"MEASURED"}
    assert {row["measured_by_user_id"] for row in rows} == {
        FUND_MANAGER_USER_ID,
        OFFICER_MEASURER_USER_ID,
    }
    assert read_fund(api, fund["id"])["compliance_posture"] == "UNTESTED"
