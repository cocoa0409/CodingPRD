"""Certification lifecycle: parallel status/HUD axes, interim recompute cascade,
finalize guards, period overlap, over-income, and OCC on tenancy version."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    setup_active_tenancy, setup_finalized_annual_cert, setup_terminated_tenancy,
    create_certification, finalize_certification,
    report_interim_change, process_interim_change,
    get_certification_by_source_interim, get_initial_certification,
)

HS = TEST_USERS["housing_specialist_headers"]

ALVAREZ_MEMBERS = [
    {"full_name": "Head A2", "relationship": "HEAD",
     "annual_income_cents": 3600000, "nonrecurring_income_cents": 240000},
    {"full_name": "Dep A", "relationship": "DEPENDENT", "annual_income_cents": 0, "is_dependent": True},
    {"full_name": "Dep B", "relationship": "DEPENDENT", "annual_income_cents": 0, "is_dependent": True},
]
SINGLE_MEMBER = [{"full_name": "Head", "relationship": "HEAD", "annual_income_cents": 3000000}]


# ---------------------------------------------------------------------------
# non_linear_state_machine / certification_parallel_status_and_hud_axes
# ---------------------------------------------------------------------------
def _setup_parallel_axes(api):
    ctx = setup_finalized_annual_cert(api, members=SINGLE_MEMBER, utility_allowance_cents=0)
    cert1 = ctx["cert"]
    get_success_data(api.hud_submit(cert1["id"], HS))
    get_success_data(api.hud_result(cert1["id"], {"result": "REJECTED"}, HS))
    get_success_data(api.hud_submit(cert1["id"], HS))
    tenancy = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    cert2 = create_certification(api, tenancy["id"], "ANNUAL", "2026-05-01T00:00:00Z", tenancy["version"])
    cert2 = finalize_certification(api, cert2["id"])
    return cert1["id"], cert2["id"]


def test_superseded_cert_keeps_independent_hud_status(api):
    """PRD §3.6: "Each certification carries an independent HUD reporting axis,
    hud_status, evolving separately from the rent-status axis". PRD §3.6: "Because the
    axes are independent, submitting or resubmitting the HUD form never changes the rent
    status."

    Design: Difficulty/non_linear_state_machine/certification_parallel_status_and_hud_axes
    """
    cert1_id, _cert2_id = _setup_parallel_axes(api)
    cert1 = get_success_data(api.get_certification(cert1_id, HS))
    assert cert1["status"] == "SUPERSEDED", "the rent axis moved to SUPERSEDED"
    assert cert1["hud_status"] == "SUBMITTED", "the HUD axis kept its own SUBMITTED value"


def test_new_effective_cert_starts_unsubmitted(api):
    """PRD §3.5: "moves the certification's status from DRAFT to EFFECTIVE, moves any
    prior effective certification on the same tenancy from EFFECTIVE to SUPERSEDED".
    PRD §3.5: "A new certification begins with status DRAFT and hud_status NOT_SUBMITTED".

    Design: Difficulty/non_linear_state_machine/certification_parallel_status_and_hud_axes
    """
    _cert1_id, cert2_id = _setup_parallel_axes(api)
    cert2 = get_success_data(api.get_certification(cert2_id, HS))
    assert cert2["status"] == "EFFECTIVE"
    assert cert2["hud_status"] == "NOT_SUBMITTED"


# ---------------------------------------------------------------------------
# transitive_cascade / interim_process_rent_recompute_chain
# ---------------------------------------------------------------------------
def test_interim_process_supersedes_prior_cert(api):
    """PRD §3.7: a processed change "creates an INTERIM certification for the tenancy ...
    then finalizes that interim certification to EFFECTIVE on the actual-income variant
    (recurring income only), supersedes the prior effective certification, and recomputes
    the tenancy's rent fields."

    Design: Difficulty/transitive_cascade/interim_process_rent_recompute_chain
    """
    ctx = setup_finalized_annual_cert(api, members=ALVAREZ_MEMBERS, utility_allowance_cents=10000)
    cert1 = ctx["cert"]
    ic = report_interim_change(api, ctx["tenancy"]["id"], ctx["applicant"]["id"],
                               "INCOME_DECREASE", "2026-05-01T00:00:00Z")
    process_interim_change(api, ic["id"], "PROCESS")
    assert get_success_data(api.get_certification(cert1["id"], HS))["status"] == "SUPERSEDED"
    interim_cert = get_certification_by_source_interim(api, ic["id"])
    assert interim_cert["status"] == "EFFECTIVE"
    assert interim_cert["ttp_cents"] == 87600


def test_interim_process_recomputes_tenant_rent(api):
    """PRD §3.5: "Whenever a certification becomes effective, the tenancy's rent fields
    are recomputed from the single latest effective certification on that tenancy ... the
    monthly_tenant_rent_cents is the Total Tenant Payment minus the utility allowance,
    floored at zero".

    Design: Difficulty/transitive_cascade/interim_process_rent_recompute_chain
    """
    ctx = setup_finalized_annual_cert(api, members=ALVAREZ_MEMBERS, utility_allowance_cents=10000)
    assert ctx["tenancy"]["monthly_tenant_rent_cents"] == 83600, "93600 TTP minus 10000 allowance"
    ic = report_interim_change(api, ctx["tenancy"]["id"], ctx["applicant"]["id"],
                               "INCOME_DECREASE", "2026-05-01T00:00:00Z")
    process_interim_change(api, ic["id"], "PROCESS")
    tenancy = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    assert tenancy["monthly_tenant_rent_cents"] == 77600, "87600 interim TTP minus 10000 allowance"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / finalize_requires_tenancy_active
# ---------------------------------------------------------------------------
def test_finalize_on_terminated_tenancy_rejected(api):
    """PRD §3.5: "the tenancy must be ACTIVE (else ERR_TENANCY_NOT_ACTIVE)".

    Design: Difficulty/cross_entity_state_dependency/finalize_requires_tenancy_active
    """
    ctx = setup_terminated_tenancy(api)
    tenancy = ctx["tenancy"]
    cert = create_certification(api, tenancy["id"], "ANNUAL", "2026-04-01T00:00:00Z", tenancy["version"])
    resp = api.finalize_certification(cert["id"], HS)
    validate_error(resp, ApiErrorId.ERR_TENANCY_NOT_ACTIVE)


def test_finalize_on_terminated_tenancy_leaves_cert_draft(api):
    """PRD §3.5: "A new certification begins with status DRAFT" and finalize is the only
    path to EFFECTIVE; a rejected finalize must leave the cert in DRAFT.

    Design: Difficulty/cross_entity_state_dependency/finalize_requires_tenancy_active
    """
    ctx = setup_terminated_tenancy(api)
    tenancy = ctx["tenancy"]
    cert = create_certification(api, tenancy["id"], "ANNUAL", "2026-04-01T00:00:00Z", tenancy["version"])
    api.finalize_certification(cert["id"], HS)
    assert get_success_data(api.get_certification(cert["id"], HS))["status"] == "DRAFT"
    assert get_success_data(api.get_tenancy(tenancy["id"], HS))["status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / cert_effective_period_equal_date_rejected
# ---------------------------------------------------------------------------
def test_cert_equal_effective_date_rejected(api):
    """PRD §3.5: "the certification's effective_date must be strictly after the
    effective_date of the tenancy's current effective certification, so equal or earlier
    dates are rejected with ERR_CERT_PERIOD_OVERLAP".

    Design: Difficulty/resource_temporal_overlap/cert_effective_period_equal_date_rejected
    """
    ctx = setup_finalized_annual_cert(api, members=SINGLE_MEMBER,
                                      effective_date="2026-04-01T00:00:00Z")
    tenancy = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    cert2 = create_certification(api, tenancy["id"], "ANNUAL", "2026-04-01T00:00:00Z", tenancy["version"])
    resp = api.finalize_certification(cert2["id"], HS)
    validate_error(resp, ApiErrorId.ERR_CERT_PERIOD_OVERLAP)


def test_cert_equal_effective_date_leaves_states_unchanged(api):
    """PRD §3.5: on overlap the request is "rejected with ERR_CERT_PERIOD_OVERLAP" — the
    prior cert stays EFFECTIVE and the rejected one stays DRAFT.

    Design: Difficulty/resource_temporal_overlap/cert_effective_period_equal_date_rejected
    """
    ctx = setup_finalized_annual_cert(api, members=SINGLE_MEMBER,
                                      effective_date="2026-04-01T00:00:00Z")
    cert1 = ctx["cert"]
    tenancy = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    cert2 = create_certification(api, tenancy["id"], "ANNUAL", "2026-04-01T00:00:00Z", tenancy["version"])
    api.finalize_certification(cert2["id"], HS)
    assert get_success_data(api.get_certification(cert2["id"], HS))["status"] == "DRAFT"
    assert get_success_data(api.get_certification(cert1["id"], HS))["status"] == "EFFECTIVE"


# ---------------------------------------------------------------------------
# boundary_precision_check / initial_cert_over_income_one_cent_over_limit
# ---------------------------------------------------------------------------
def test_initial_cert_one_cent_over_income_limit_rejected(api):
    """PRD §3.5: "for an INITIAL certification only, the household's anticipated annual
    gross income must not exceed the unit's income_limit_cents — an equal figure passes,
    a strictly greater one is rejected with ERR_OVER_INCOME."

    Design: Difficulty/boundary_precision_check/initial_cert_over_income_one_cent_over_limit
    """
    ctx = setup_active_tenancy(
        api, members=[{"full_name": "Head O", "relationship": "HEAD", "annual_income_cents": 3600001}],
        income_limit_cents=3600000)
    init_cert = get_initial_certification(api, ctx["tenancy"]["id"])
    resp = api.finalize_certification(init_cert["id"], HS)
    validate_error(resp, ApiErrorId.ERR_OVER_INCOME)


def test_initial_cert_over_income_leaves_cert_draft(api):
    """PRD §3.5: a rejected finalize does not lock in rent, so the INITIAL cert stays in
    DRAFT ("A new certification begins with status DRAFT").

    Design: Difficulty/boundary_precision_check/initial_cert_over_income_one_cent_over_limit
    """
    ctx = setup_active_tenancy(
        api, members=[{"full_name": "Head O", "relationship": "HEAD", "annual_income_cents": 3600001}],
        income_limit_cents=3600000)
    init_cert = get_initial_certification(api, ctx["tenancy"]["id"])
    api.finalize_certification(init_cert["id"], HS)
    assert get_success_data(api.get_certification(init_cert["id"], HS))["status"] == "DRAFT"


def test_initial_cert_income_exactly_at_limit_passes(api):
    """PRD §3.5: "an equal figure passes, a strictly greater one is rejected with
    ERR_OVER_INCOME." At exactly the limit the finalize must succeed.

    Design: Difficulty/boundary_precision_check/initial_cert_over_income_one_cent_over_limit
    """
    ctx = setup_active_tenancy(
        api, members=[{"full_name": "Head E", "relationship": "HEAD", "annual_income_cents": 3600000}],
        income_limit_cents=3600000)
    init_cert = get_initial_certification(api, ctx["tenancy"]["id"])
    finalized = validate_success(api.finalize_certification(init_cert["id"], HS))
    assert finalized["status"] == "EFFECTIVE"


# ---------------------------------------------------------------------------
# Corner: hud_result_before_submit_rejected
# ---------------------------------------------------------------------------
def test_hud_result_before_submit_rejected(api):
    """PRD §3.6: "Only a certification whose hud_status is SUBMITTED may receive a
    result; otherwise ERR_INVALID_STATE is returned."

    Design: Corner/state_machines/hud_result_before_submit_rejected
    """
    ctx = setup_finalized_annual_cert(api, members=SINGLE_MEMBER)
    resp = api.hud_result(ctx["cert"]["id"], {"result": "ACCEPTED"}, HS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: OCC on tenancy version
# ---------------------------------------------------------------------------
def test_stale_tenancy_version_create_rejected(api):
    """PRD §2.6: "If expected_tenancy_version does not equal the tenancy's current
    version, the create is rejected with ERR_STALE_VERSION (HTTP 412). ... A successful
    create increments the tenancy's version by one, so a second create replaying the same
    expected_tenancy_version will also be rejected."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_tenancy_version_rejected
    """
    ctx = setup_active_tenancy(api, members=SINGLE_MEMBER)
    t_v = ctx["tenancy"]["version"]
    create_certification(api, ctx["tenancy"]["id"], "ANNUAL", "2026-04-01T00:00:00Z", t_v)
    resp = api.create_certification(
        ctx["tenancy"]["id"],
        {"cert_type": "ANNUAL", "effective_date": "2026-06-01T00:00:00Z", "expected_tenancy_version": t_v},
        HS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_current_version_create_bumps_tenancy_version(api):
    """PRD §2.6: "A request to create a new certification for a tenancy must carry
    expected_tenancy_version ... A successful create increments the tenancy's version by
    one".

    Design: Corner/cross_cutting_complexity_layers/occ_current_version_create_succeeds_and_bumps
    """
    ctx = setup_active_tenancy(api, members=SINGLE_MEMBER)
    t_v = ctx["tenancy"]["version"]
    resp = api.create_certification(
        ctx["tenancy"]["id"],
        {"cert_type": "ANNUAL", "effective_date": "2026-04-01T00:00:00Z", "expected_tenancy_version": t_v},
        HS)
    cert = validate_success(resp, expected_status=201)
    assert cert["status"] == "DRAFT"
    tenancy = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    assert tenancy["version"] == t_v + 1, "a successful create increments the tenancy version by one"


# ---------------------------------------------------------------------------
# Corner: cert_create_unknown_tenancy_returns_404
# ---------------------------------------------------------------------------
def test_cert_create_unknown_tenancy_returns_404(api):
    """PRD §2.5: "the system resolves them left to right and rejects the request at the
    first identifier that does not correspond to a live resource, returning the not-found
    error specific to that resource — ... ERR_TENANCY_NOT_FOUND ... (all HTTP 404)."

    Design: Corner/errors/cert_create_unknown_tenancy_returns_404
    """
    resp = api.create_certification(
        NON_EXISTENT_UUID,
        {"cert_type": "ANNUAL", "effective_date": "2026-04-01T00:00:00Z", "expected_tenancy_version": 1},
        HS)
    validate_error(resp, ApiErrorId.ERR_TENANCY_NOT_FOUND)
