"""Spending-policy parameter ranges, half-open effective windows, OCC, segregation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_policy_payload,
    create_pool,
    get_pool,
    get_success_data,
    make_board_member_headers,
    make_investment_officer_headers,
    set_target_allocations,
    setup_pool_world,
    validate_error,
    validate_success,
)


def _propose_policy(api, pool_id, effective_year, rate=500, proposer="io-1"):
    return get_success_data(api.create_policy(
        create_policy_payload(pool_id, spending_rate_bps=rate,
                              effective_from_fiscal_year=effective_year),
        make_investment_officer_headers(proposer),
    ))


def test_policy_parameter_ranges_enforced(api):
    """PRD §3.3: 'An `InvestmentOfficer` proposes spending policy versions against a
    pool, supplying `pool_id`, an annual `spending_rate_bps` between 100 and 2000
    inclusive (1.00% to 20.00%), a `smoothing_window_quarters` between 4 and 20
    inclusive, a `band_floor_bps` and `band_cap_bps` each between 0 and 10000
    inclusive, and an `effective_from_fiscal_year`.'
    PRD §3.3: 'Parameters outside these ranges are rejected with
    `ERR_POLICY_PARAM_OUT_OF_RANGE`.'

    Design: Corner/validations/policy_parameter_ranges_enforced
    """
    pool = create_pool(pool_name="Pool PR", inception_fiscal_year=2026)

    res1 = api.create_policy(
        create_policy_payload(pool["id"], spending_rate_bps=2001),
        TEST_USERS["io_headers"],
    )
    validate_error(res1, ApiErrorId.ERR_POLICY_PARAM_OUT_OF_RANGE, 422)

    res2 = api.create_policy(
        create_policy_payload(pool["id"], spending_rate_bps=500,
                              smoothing_window_quarters=3),
        TEST_USERS["io_headers"],
    )
    validate_error(res2, ApiErrorId.ERR_POLICY_PARAM_OUT_OF_RANGE, 422)

    ok = validate_success(api.create_policy(
        create_policy_payload(pool["id"], spending_rate_bps=2000,
                              smoothing_window_quarters=4),
        TEST_USERS["io_headers"],
    ), 201)
    assert ok["policy_status"] == "DRAFT"


def test_policy_adopt_equal_effective_year_conflicts(api):
    """PRD §3.3: 'Two window rules apply, both failing as `ERR_WINDOW_CONFLICT`: no
    already-`ADOPTED` policy of the same pool may share the candidate's
    `effective_from_fiscal_year`, and the candidate's effective year must be strictly
    greater than every other `ADOPTED` policy's effective year for that pool, so the
    adopted policies form a strictly increasing sequence of half-open windows
    [effective year of policy *i*, effective year of policy *i*+1).'

    Design: Difficulty/resource_temporal_overlap/policy_effective_year_windows_half_open_strictly_increasing
    """
    pool = create_pool(pool_name="Pool PW", inception_fiscal_year=2026)
    set_target_allocations(pool["id"])
    policy_a = _propose_policy(api, pool["id"], 2026, rate=500)
    validate_success(api.adopt_policy(
        policy_a["id"], {"expected_pool_version": get_pool(pool["id"])["version"]},
        make_board_member_headers("bm-1"),
    ), 200)
    policy_b = _propose_policy(api, pool["id"], 2026, rate=550)

    res = api.adopt_policy(
        policy_b["id"], {"expected_pool_version": get_pool(pool["id"])["version"]},
        make_board_member_headers("bm-1"),
    )
    validate_error(res, ApiErrorId.ERR_WINDOW_CONFLICT, 409)

    still = get_success_data(api.get_policy(policy_b["id"], TEST_USERS["io_headers"]))
    assert still["policy_status"] == "DRAFT"


def test_policy_adopt_later_year_supersedes_prior(api):
    """PRD §3.3: 'When adoption succeeds, the pool's previously latest `ADOPTED`
    policy, if any, transitions from `ADOPTED` to `SUPERSEDED` — its window closes
    but it still governs its past fiscal years for historical lookups — the new
    policy records `adopted_by_user_id`, and the pool's `version` increments by 1.'

    Design: Difficulty/resource_temporal_overlap/policy_effective_year_windows_half_open_strictly_increasing
    """
    pool = create_pool(pool_name="Pool PW", inception_fiscal_year=2026)
    set_target_allocations(pool["id"])
    policy_a = _propose_policy(api, pool["id"], 2026, rate=500)
    validate_success(api.adopt_policy(
        policy_a["id"], {"expected_pool_version": get_pool(pool["id"])["version"]},
        make_board_member_headers("bm-1"),
    ), 200)
    policy_b = _propose_policy(api, pool["id"], 2026, rate=550)
    policy_c = _propose_policy(api, pool["id"], 2028, rate=550)

    # Equal-year adoption fails and must not consume the pool version.
    version_after_failure = get_pool(pool["id"])["version"]
    res = api.adopt_policy(
        policy_b["id"], {"expected_pool_version": version_after_failure},
        make_board_member_headers("bm-1"),
    )
    validate_error(res, ApiErrorId.ERR_WINDOW_CONFLICT, 409)

    adopted = validate_success(api.adopt_policy(
        policy_c["id"], {"expected_pool_version": get_pool(pool["id"])["version"]},
        make_board_member_headers("bm-1"),
    ), 200)
    assert adopted["policy_status"] == "ADOPTED"
    assert adopted["adopted_by_user_id"] == "bm-1"

    superseded = get_success_data(api.get_policy(policy_a["id"], TEST_USERS["io_headers"]))
    assert superseded["policy_status"] == "SUPERSEDED"


def test_occ_policy_adopt_rejected_with_stale_pool_version(api):
    """PRD §2.7: 'If the pool's current `version` has advanced since that read — for
    example because a suspend/resume cycle or another finalize intervened — the
    request is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412).'
    PRD §3.3: 'Adoption is a `BoardMember` action requiring the pool to be `ACTIVE`
    and carrying the OCC token `expected_pool_version` (§2.7).'

    Design: Corner/cross_cutting_complexity_layers/occ_policy_adopt_rejected_with_stale_pool_version
    """
    pool = create_pool(pool_name="Pool OA", inception_fiscal_year=2026)
    stale_version = pool["version"]
    policy_a = _propose_policy(api, pool["id"], 2026, rate=500)
    policy_b = _propose_policy(api, pool["id"], 2027, rate=550)

    adopted_a = validate_success(api.adopt_policy(
        policy_a["id"], {"expected_pool_version": stale_version},
        make_board_member_headers("bm-1"),
    ), 200)
    assert adopted_a["policy_status"] == "ADOPTED"

    res = api.adopt_policy(
        policy_b["id"], {"expected_pool_version": stale_version},
        make_board_member_headers("bm-1"),
    )
    validate_error(res, ApiErrorId.ERR_STALE_POOL_VERSION, 412)

    adopted_b = validate_success(api.adopt_policy(
        policy_b["id"], {"expected_pool_version": get_pool(pool["id"])["version"]},
        make_board_member_headers("bm-1"),
    ), 200)
    assert adopted_b["policy_status"] == "ADOPTED"

    superseded_a = get_success_data(api.get_policy(policy_a["id"], TEST_USERS["io_headers"]))
    assert superseded_a["policy_status"] == "SUPERSEDED"


def test_segregation_of_duties_policy_adopter_must_differ_from_proposer(api):
    """PRD §2.1: 'adopting a policy requires the adopter's `X-User-ID` to differ from
    the policy's `proposed_by_user_id`;'
    PRD §2.1: 'Any breach of these rules is rejected with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).'

    Design: Corner/rbac/segregation_of_duties_policy_adopter_must_differ_from_proposer
    """
    pool = create_pool(pool_name="Pool SD", inception_fiscal_year=2026)
    policy = _propose_policy(api, pool["id"], 2026, rate=500, proposer="dual-1")

    res = api.adopt_policy(
        policy["id"], {"expected_pool_version": get_pool(pool["id"])["version"]},
        make_board_member_headers("dual-1"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)

    still = get_success_data(api.get_policy(policy["id"], TEST_USERS["io_headers"]))
    assert still["policy_status"] == "DRAFT"

    adopted = validate_success(api.adopt_policy(
        policy["id"], {"expected_pool_version": get_pool(pool["id"])["version"]},
        make_board_member_headers("bm-9"),
    ), 200)
    assert adopted["policy_status"] == "ADOPTED"
