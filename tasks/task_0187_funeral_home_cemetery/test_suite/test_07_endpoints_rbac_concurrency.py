"""Action endpoints, computed reads, RBAC denials, segregation of duties,
authentication, and optimistic-concurrency conflicts.

Queue B (Corner) — sections: endpoints, errors, rbac, cross_cutting.
"""
from test_helpers import (
    TEST_USERS, make_headers,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_funeral_home, create_gpl_item, create_venue, create_plot,
    create_case, create_disclosed_case, add_line, create_contract,
    setup_arranged_case, post_principal, submit_for_funding,
    current_contract_version, reserve_plot, apply_permit, schedule_chapel,
)

ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]
TRUST = TEST_USERS["trust_officer_headers"]
CLERK = TEST_USERS["cemetery_clerk_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ==========================================================================
# endpoints
# ==========================================================================
def test_cancel_event_frees_interval_then_reschedule_succeeds(api):
    """PRD §3.9: "An Arranger may cancel a scheduled event; cancellation is
    allowed only when the event is SCHEDULED ... moves the event to CANCELLED ...
    and frees the resource interval so a later overlapping booking on the same
    venue or plot succeeds."

    Design: Corner/endpoints/cancel_event_frees_resource_then_reschedule_succeeds
    """
    home = create_funeral_home(chapel_buffer_minutes=30)
    venue = create_venue(home["id"], name="Main Chapel", capacity=100)
    case1 = create_case(home["id"], decedent_name="Case One", case_mode="AT_NEED",
                        date_of_death="2026-06-01T00:00:00.000Z")
    ev1 = schedule_chapel(case1["id"], venue["id"],
                          "2026-06-10T15:00:00.000Z", "2026-06-10T16:00:00.000Z")

    cancelled = validate_success(api.cancel_event(case1["id"], ev1["id"], ARRANGER))
    assert cancelled["status"] == "CANCELLED"

    ev2 = validate_success(api.create_event(case1["id"], {
        "resource_kind": "CHAPEL", "resource_id": venue["id"],
        "starts_at": "2026-06-10T15:30:00.000Z", "ends_at": "2026-06-10T16:30:00.000Z"
    }, ARRANGER), expected_status=201)
    assert ev2["status"] == "SCHEDULED"


def test_reserve_already_reserved_plot_rejected(api):
    """PRD §3.8: "Reservation is allowed only when the plot is AVAILABLE — a plot
    not in AVAILABLE is rejected with ERR_PLOT_NOT_AVAILABLE (HTTP 409)".

    Design: Corner/endpoints/reserve_already_reserved_plot_returns_plot_not_available
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-5", current_price_cents=80000)
    case1 = create_case(home["id"], decedent_name="Case One", case_mode="AT_NEED",
                        date_of_death="2026-06-01T00:00:00.000Z")
    case2 = create_case(home["id"], decedent_name="Case Two", case_mode="AT_NEED",
                        date_of_death="2026-06-02T00:00:00.000Z")
    reserved = reserve_plot(plot["id"], case1["id"], plot["version"])

    resp = api.reserve_plot(
        plot["id"], {"case_id": case2["id"], "expected_plot_version": reserved["version"]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_PLOT_NOT_AVAILABLE.value)

    after = validate_success(api.get_plot(plot["id"], CLERK))
    assert after["reserved_case_id"] == case1["id"]


def test_release_available_plot_rejected(api):
    """PRD §3.8: "Release is allowed only when the plot is RESERVED — releasing a
    plot not in RESERVED is rejected with ERR_PLOT_NOT_RESERVED (HTTP 409)".

    Design: Corner/endpoints/release_available_plot_returns_plot_not_reserved
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-6", current_price_cents=80000)

    resp = api.release_plot(plot["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_PLOT_NOT_RESERVED.value)

    after = validate_success(api.get_plot(plot["id"], CLERK))
    assert after["status"] == "AVAILABLE"


def test_second_contract_for_case_rejected(api):
    """PRD §3.4: "Attempting to create a second contract for a case that already
    has one is rejected with ERR_CONTRACT_EXISTS (HTTP 409)."

    Design: Corner/endpoints/second_contract_for_case_returns_contract_exists
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    create_contract(case["id"], "AT_NEED_DIRECT")

    resp = api.create_contract(case["id"], {"funding_type": "PRENEED_TRUST"}, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_EXISTS.value)


def test_funeral_home_trust_balance_computed_read(api):
    """PRD §2.8: "Each funeral home additionally exposes a rolled-up
    trust_balance_cents, a conserved global quantity equal to the sum, across all
    of that home's contracts, of each contract's principal corpus plus its
    credited earnings."

    After a 360000 PRINCIPAL deposit, GET /funeral-homes/{id} reports
    trust_balance_cents == 360000.

    Design: Corner/endpoints/funeral_home_trust_balance_computed_read
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, preneed_trustable=True, unit_price_cents=200000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 360000)

    data = validate_success(api.get_funeral_home(home["id"], TRUST))
    assert data["trust_balance_cents"] == 360000
    contract_after = validate_success(api.get_contract(contract["id"], TRUST))
    assert contract_after["trust_principal_cents"] == 360000


# ==========================================================================
# errors
# ==========================================================================
def test_unknown_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    home = create_funeral_home()
    bad_headers = make_headers("x-1", "NobodyRole")

    resp = api.get_funeral_home(home["id"], bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


# ==========================================================================
# rbac
# ==========================================================================
def test_arranger_cannot_mark_contract_funded(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not
    authorized to perform, the request is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4 (POST /contracts/{contractId}/mark-funded): authorized role TrustOfficer.

    Design: Corner/rbac/arranger_cannot_mark_contract_funded_returns_forbidden
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=100000)
    post_principal(contract["id"], 100000)
    submit_for_funding(contract["id"])
    c_v = current_contract_version(contract["id"])

    resp = api.mark_funded(contract["id"], {"expected_contract_version": c_v}, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    after = validate_success(api.get_contract(contract["id"], TRUST))
    assert after["status"] == "PENDING_FUNDING"


def test_cemetery_clerk_cannot_issue_permit(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not
    authorized to perform, the request is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4 (POST /permits/{permitId}/issue): authorized role Registrar.

    Design: Corner/rbac/cemetery_clerk_cannot_issue_permit_returns_forbidden
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")

    resp = api.issue_permit(dc["id"], {"reference_number": "DC-X"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    after = validate_success(api.get_permit(dc["id"], REGISTRAR))
    assert after["status"] == "APPLIED"


def test_same_user_disclose_and_fund_returns_segregation_of_duties(api):
    """PRD §3.6: "The funding officer's X-User-ID must differ from the case's
    recorded disclosure_officer_id — the Arranger who acknowledged the disclosure
    may not also fund the contract — and a match is rejected with
    ERR_SEGREGATION_OF_DUTIES (HTTP 409)."

    The same identity (u-shared) acknowledges disclosure as Arranger and then
    marks the contract funded as TrustOfficer.

    Design: Corner/rbac/segregation_of_duties_same_user_funds_returns_error
    """
    shared_arranger = make_headers("u-shared", "Arranger")
    shared_trust = make_headers("u-shared", "TrustOfficer")
    other_trust = make_headers("to-9", "TrustOfficer")

    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, unit_price_cents=100000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z",
                       arranger_headers=shared_arranger)
    get_success_data(api.acknowledge_disclosure(case["id"], shared_arranger))
    add_line(case["id"], svc["id"], arranger_headers=shared_arranger)
    contract = create_contract(case["id"], "AT_NEED_DIRECT", arranger_headers=shared_arranger)
    get_success_data(api.issue_gfs(case["id"], shared_arranger))
    post_principal(contract["id"], 100000, trust_headers=other_trust)
    submit_for_funding(contract["id"], arranger_headers=shared_arranger)
    c_v = current_contract_version(contract["id"], other_trust)

    resp = api.mark_funded(contract["id"], {"expected_contract_version": c_v}, shared_trust)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = validate_success(api.get_contract(contract["id"], other_trust))
    assert after["status"] == "PENDING_FUNDING"


# ==========================================================================
# cross_cutting (optimistic concurrency)
# ==========================================================================
def test_reserve_plot_stale_version_rejected(api):
    """PRD §2.7: "A reserve-a-plot request must include expected_plot_version as a
    required field carrying the client's last observed version of the target plot.
    If that value does not match the plot's current version ... the request is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    A reserve then release advances the version past the originally observed v0; a
    second reserve carrying v0 is stale.

    Design: Corner/cross_cutting/plot_reserve_stale_version_conflict
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-30", current_price_cents=80000)
    v0 = plot["version"]
    case1 = create_case(home["id"], decedent_name="Case One", case_mode="AT_NEED",
                        date_of_death="2026-06-01T00:00:00.000Z")
    case2 = create_case(home["id"], decedent_name="Case Two", case_mode="AT_NEED",
                        date_of_death="2026-06-02T00:00:00.000Z")
    reserve_plot(plot["id"], case1["id"], v0)
    get_success_data(api.release_plot(plot["id"], CLERK))

    resp = api.reserve_plot(
        plot["id"], {"case_id": case2["id"], "expected_plot_version": v0}, CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_mark_funded_stale_contract_version_rejected(api):
    """PRD §2.7: "Posting a trust deposit or verifying an insurance assignment
    silently advances a contract's version ... if such a change has occurred since
    the client read the contract, the supplied expected_contract_version will no
    longer match the contract's current version and the request is rejected with
    ERR_STALE_VERSION (HTTP 412)".

    Client reads version c_v0; a second deposit bumps it; mark-funded with c_v0 is
    stale.

    Design: Corner/cross_cutting/contract_mark_funded_stale_version_conflict
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=100000)
    post_principal(contract["id"], 60000)
    submit_for_funding(contract["id"])
    c_v0 = current_contract_version(contract["id"])
    post_principal(contract["id"], 40000)  # bumps version past c_v0

    resp = api.mark_funded(contract["id"], {"expected_contract_version": c_v0}, TRUST)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    after = validate_success(api.get_contract(contract["id"], TRUST))
    assert after["status"] == "PENDING_FUNDING"
