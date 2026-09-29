"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the API before each test, so nothing is
ever carried over. Helpers use the lenient `get_success_data` validator so a
broken precondition surfaces as a setup failure rather than as a confusing
assertion inside the test under study.

The `Investor` role's `X-User-ID` equals `Investor.id`, so every
ownership-gated investor call below threads the real investor id through
`make_investor_headers`.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_STARTUP, TEST_DEFAULTS
from .factories import (
    create_capital_need_payload,
    create_distribution_payload,
    create_exchange_file_payload,
    create_exit_consent_payload,
    create_exit_event_payload,
    create_identification_payload,
    create_investor_payload,
    create_loan_facility_payload,
    create_master_lease_payload,
    create_offering_payload,
    create_property_payload,
    create_subscription_payload,
    create_tax_statement_payload,
    create_trust_payload,
    debt_service_payment_payload,
    rent_posting_payload,
)
from .test_users import (
    TEST_USERS,
    make_investor_headers,
    make_master_tenant_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
QI = TEST_USERS["qi_headers"]
TENANT = TEST_USERS["master_tenant_headers"]


# --------------------------------------------------------------------------
# Instants used by the composite scenarios below.
# --------------------------------------------------------------------------

CLOCK = {
    "START": CLOCK_STARTUP,
    "PRE_ACQUISITION": "2026-08-20T00:00:00Z",
    "SUB_A_CLOSE": "2026-09-15T00:00:00Z",
    "IDENTIFICATION_DEADLINE_A": "2026-09-19T23:59:59.999Z",
    "PAST_IDENTIFICATION_DEADLINE_A": "2026-09-20T00:00:00.000Z",
    "OCTOBER": "2026-10-01T00:00:00Z",
    "SUB_B_REVIEW": "2026-11-01T00:00:00Z",
    "SUB_B_CLOSE": "2026-11-20T00:00:00Z",
    "DECEMBER": "2026-12-01T00:00:00Z",
    "MID_DECEMBER": "2026-12-15T00:00:00Z",
    "NEW_YEAR": "2027-01-02T00:00:00Z",
    "FEBRUARY": "2027-02-01T00:00:00Z",
    "MARCH": "2027-03-01T00:00:00Z",
    "APRIL": "2027-04-02T00:00:00Z",
}


# --------------------------------------------------------------------------
# Primitives — one call each.
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_property(**overrides) -> dict:
    return get_success_data(
        api.create_property(create_property_payload(**overrides), SPONSOR)
    )


def acquire_property(property_id: str) -> dict:
    return get_success_data(api.acquire_property(property_id, SPONSOR))


def expire_property_contract(property_id: str) -> dict:
    return get_success_data(api.expire_property_contract(property_id, SPONSOR))


def create_trust(property_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_trust(create_trust_payload(property_id, **overrides), TRUSTEE)
    )


def create_offering(trust_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_offering(create_offering_payload(trust_id, **overrides), SPONSOR)
    )


def submit_ppm(offering_id: str, reference: str = "PPM-2423-r1", headers=None) -> dict:
    return get_success_data(
        api.submit_ppm(
            offering_id, {"ppm_document_reference": reference}, headers or SPONSOR
        )
    )


def return_ppm(offering_id: str, review_note: str = "restate the reserve policy") -> dict:
    return get_success_data(
        api.return_ppm(offering_id, COMPLIANCE, {"review_note": review_note})
    )


def declare_offering_effective(
    offering_id: str, acknowledged_ppm_version: int = 1, headers=None
) -> dict:
    return get_success_data(
        api.declare_offering_effective(
            offering_id,
            {"acknowledged_ppm_version": acknowledged_ppm_version},
            headers or COMPLIANCE,
        )
    )


def withdraw_offering(offering_id: str, reason: str = "sponsor pulled the deal") -> dict:
    return get_success_data(
        api.withdraw_offering(offering_id, COMPLIANCE, {"reason": reason})
    )


def create_loan_facility(trust_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_loan_facility(
            create_loan_facility_payload(trust_id, **overrides), TRUSTEE
        )
    )


def fund_loan_facility(loan_id: str) -> dict:
    return get_success_data(api.fund_loan_facility(loan_id, TRUSTEE))


def open_trust_funding(trust_id: str) -> dict:
    return get_success_data(api.open_trust_funding(trust_id, TRUSTEE))


def create_master_lease(trust_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_master_lease(
            create_master_lease_payload(trust_id, **overrides), TRUSTEE
        )
    )


def execute_master_lease(lease_id: str) -> dict:
    return get_success_data(api.execute_master_lease(lease_id, TRUSTEE))


def create_investor(**overrides) -> dict:
    return get_success_data(
        api.create_investor(create_investor_payload(**overrides), SPONSOR)
    )


def verify_accreditation(investor_id: str, evidence_reference: str) -> dict:
    return get_success_data(
        api.verify_accreditation(
            investor_id, {"evidence_reference": evidence_reference}, COMPLIANCE
        )
    )


def lapse_accreditation(investor_id: str) -> dict:
    return get_success_data(api.lapse_accreditation(investor_id, COMPLIANCE))


def review_suitability(
    investor_id: str, offering_id: str, decision: str = "APPROVED", headers=None
) -> dict:
    return get_success_data(
        api.review_suitability(
            investor_id,
            {"decision": decision, "offering_id": offering_id},
            headers or COMPLIANCE,
        )
    )


def create_exchange_file(investor_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_exchange_file(
            create_exchange_file_payload(investor_id, **overrides), QI
        )
    )


def mark_exchange_file_expired(exchange_file_id: str) -> dict:
    return get_success_data(api.mark_exchange_file_expired(exchange_file_id, QI))


def file_identification(exchange_file_id: str, property_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_identification(
            create_identification_payload(exchange_file_id, property_id, **overrides), QI
        )
    )


def revoke_identification(identification_id: str, reason: str = "withdrawn") -> dict:
    return get_success_data(
        api.revoke_identification(identification_id, QI, {"reason": reason})
    )


def create_subscription(
    offering_id: str,
    investor_id: str,
    exchange_file_id: str,
    units_requested: int,
    expected_offering_version: int,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_subscription(
            create_subscription_payload(
                offering_id,
                investor_id,
                exchange_file_id,
                units_requested,
                expected_offering_version,
                **overrides,
            ),
            SPONSOR,
        )
    )


def close_subscription(subscription_id: str, headers=None) -> dict:
    return get_success_data(
        api.close_subscription(subscription_id, headers or SPONSOR)
    )


def rescind_subscription(subscription_id: str, investor_id: str) -> dict:
    return get_success_data(
        api.rescind_subscription(subscription_id, make_investor_headers(investor_id))
    )


def post_rent(
    trust_id: str, master_tenant_user_id: str = None, **overrides
) -> dict:
    tenant_id = master_tenant_user_id or TEST_DEFAULTS["MASTER_TENANT_USER_ID"]
    return get_success_data(
        api.post_rent(
            trust_id,
            rent_posting_payload(**overrides),
            make_master_tenant_headers(tenant_id),
        )
    )


def post_debt_service(trust_id: str, **overrides) -> dict:
    return get_success_data(
        api.post_debt_service_payment(
            trust_id, debt_service_payment_payload(**overrides), TRUSTEE
        )
    )


def create_capital_need(trust_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_capital_need(
            create_capital_need_payload(trust_id, **overrides), headers or TRUSTEE
        )
    )


def fund_capital_need(capital_need_id: str, funding_source: str, headers=None) -> dict:
    return get_success_data(
        api.fund_capital_need(
            capital_need_id, {"funding_source": funding_source}, headers or TRUSTEE
        )
    )


def void_capital_need(capital_need_id: str, reason: str = "work cancelled") -> dict:
    return get_success_data(
        api.void_capital_need(capital_need_id, TRUSTEE, {"reason": reason})
    )


def declare_distribution(trust_id: str, expected_trust_version: int, **overrides) -> dict:
    return get_success_data(
        api.create_distribution(
            create_distribution_payload(trust_id, expected_trust_version, **overrides),
            TRUSTEE,
        )
    )


def pay_distribution(distribution_id: str) -> dict:
    return get_success_data(api.pay_distribution(distribution_id, TRUSTEE))


def create_tax_statement(trust_id: str, subscription_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_tax_statement(
            create_tax_statement_payload(trust_id, subscription_id, **overrides), SPONSOR
        )
    )


def create_exit_event(trust_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_exit_event(create_exit_event_payload(trust_id, **overrides), SPONSOR)
    )


def record_exit_consent(
    exit_event_id: str, subscription_id: str, investor_id: str, decision: str = "CONSENT"
) -> dict:
    return get_success_data(
        api.create_exit_consent(
            create_exit_consent_payload(
                exit_event_id, subscription_id, decision=decision
            ),
            make_investor_headers(investor_id),
        )
    )


def tally_consents(exit_event_id: str) -> dict:
    return get_success_data(api.tally_consents(exit_event_id, SPONSOR))


def close_exit_event(exit_event_id: str) -> dict:
    return get_success_data(api.close_exit_event(exit_event_id, TRUSTEE))


# --------------------------------------------------------------------------
# Reads used to thread concurrency tokens and to discover cascade rows.
# --------------------------------------------------------------------------


def read_property(property_id: str) -> dict:
    return get_success_data(api.get_property(property_id, SPONSOR))


def read_trust(trust_id: str) -> dict:
    return get_success_data(api.get_trust(trust_id, TRUSTEE))


def read_offering(offering_id: str) -> dict:
    return get_success_data(api.get_offering(offering_id, SPONSOR))


def read_subscription(subscription_id: str) -> dict:
    return get_success_data(api.get_subscription(subscription_id, SPONSOR))


def read_investor(investor_id: str) -> dict:
    return get_success_data(api.get_investor(investor_id, COMPLIANCE))


def read_exchange_file(exchange_file_id: str) -> dict:
    return get_success_data(api.get_exchange_file(exchange_file_id, QI))


def read_loan_facility(loan_id: str) -> dict:
    return get_success_data(api.get_loan_facility(loan_id, TRUSTEE))


def read_distribution(distribution_id: str) -> dict:
    return get_success_data(api.get_distribution(distribution_id, TRUSTEE))


def read_capital_need(capital_need_id: str) -> dict:
    return get_success_data(api.get_capital_need(capital_need_id, TRUSTEE))


def read_exit_event(exit_event_id: str) -> dict:
    return get_success_data(api.get_exit_event(exit_event_id, SPONSOR))


def trust_version(trust_id: str) -> int:
    return read_trust(trust_id)["version"]


def offering_version(offering_id: str) -> int:
    return read_offering(offering_id)["version"]


def _rows(response) -> list:
    data = response.json().get("data")
    assert isinstance(data, list), f"Expected a list payload, got {data!r}"
    assert 200 <= response.status_code < 300, (
        f"Setup list read failed with {response.status_code}: {response.text}"
    )
    return data


def list_ledger_entries(trust_id: str, **filters) -> list:
    params = {"trust_id": trust_id, "limit": 100}
    params.update(filters)
    return _rows(api.list_ledger_entries(TRUSTEE, params=params))


def list_subscriptions_for_offering(offering_id: str, **filters) -> list:
    params = {"offering_id": offering_id, "limit": 100}
    params.update(filters)
    return _rows(api.list_subscriptions(SPONSOR, params=params))


def list_allocations(distribution_id: str) -> list:
    return _rows(
        api.list_distribution_allocations(
            TRUSTEE, params={"distribution_id": distribution_id, "limit": 100}
        )
    )


def list_exchange_files_for_exit(exit_event_id: str) -> list:
    return _rows(
        api.list_exchange_files(
            QI, params={"source_exit_event_id": exit_event_id, "limit": 100}
        )
    )


def find_ledger_entry(trust_id: str, entry_type: str, bucket: str = None) -> dict:
    filters = {"entry_type": entry_type}
    if bucket:
        filters["bucket"] = bucket
    rows = list_ledger_entries(trust_id, **filters)
    assert rows, f"Setup expected at least one {entry_type} entry on trust {trust_id}"
    return rows[0]


# --------------------------------------------------------------------------
# Tier 1 / 2 — the deal spine.
# --------------------------------------------------------------------------


def setup_trust_forming(property=None, trust=None) -> dict:
    """Clock at startup, one property under contract, one FORMING trust."""
    set_clock(CLOCK["START"])
    prop = create_property(**(property or {}))
    dst = create_trust(prop["id"], **(trust or {}))
    return {"property": prop, "trust": dst}


def setup_offering_and_loan(
    property=None, trust=None, offering=None, loan=None
) -> dict:
    """FORMING trust with a DRAFT offering and a COMMITTED facility."""
    deal = setup_trust_forming(property=property, trust=trust)
    deal["offering"] = create_offering(deal["trust"]["id"], **(offering or {}))
    deal["loan"] = create_loan_facility(deal["trust"]["id"], **(loan or {}))
    return deal


def setup_offering_under_review(
    property=None, trust=None, offering=None, loan=None
) -> dict:
    """Property ACQUIRED and the memorandum submitted, so the offering is
    UNDER_REVIEW and its capital stack is about to be pinned."""
    deal = setup_offering_and_loan(
        property=property, trust=trust, offering=offering, loan=loan
    )
    set_clock(CLOCK["PRE_ACQUISITION"])
    deal["property"] = acquire_property(deal["property"]["id"])
    deal["offering"] = submit_ppm(deal["offering"]["id"])
    return deal


def setup_offering_effective(
    property=None, trust=None, offering=None, loan=None
) -> dict:
    """The offering is EFFECTIVE with the grossed-up capital stack pinned."""
    deal = setup_offering_under_review(
        property=property, trust=trust, offering=offering, loan=loan
    )
    deal["offering"] = declare_offering_effective(deal["offering"]["id"], 1)
    deal["offering_version"] = deal["offering"]["version"]
    return deal


def setup_trust_funding(property=None, trust=None, offering=None, loan=None) -> dict:
    """The trust is FUNDING: facility FUNDED, offering EFFECTIVE, funding open."""
    deal = setup_offering_effective(
        property=property, trust=trust, offering=offering, loan=loan
    )
    # Opening funding comes first: a facility may only be drawn while the trust
    # is FUNDING, and opening funding accepts a facility that is still COMMITTED.
    deal["trust"] = open_trust_funding(deal["trust"]["id"])
    deal["loan"] = fund_loan_facility(deal["loan"]["id"])
    deal["trust"] = read_trust(deal["trust"]["id"])
    return deal


def setup_trust_funding_with_lease(
    property=None, trust=None, offering=None, loan=None, lease=None
) -> dict:
    """FUNDING trust whose master lease is already EXECUTED, so a completed
    raise can carry the trust all the way to OPERATING."""
    deal = setup_trust_funding(
        property=property, trust=trust, offering=offering, loan=loan
    )
    deal["lease"] = create_master_lease(deal["trust"]["id"], **(lease or {}))
    deal["lease"] = execute_master_lease(deal["lease"]["id"])
    return deal


# --------------------------------------------------------------------------
# Tier 3 — qualified investors and reserved subscriptions.
# --------------------------------------------------------------------------

INVESTOR_A = {
    "legal_name": "Alice Adams",
    "entity_type": "INDIVIDUAL",
    "accreditation_method": "SELF_CERT_NET_WORTH",
    "annual_income_cents": 90_000_000,
    "net_worth_cents": 2_000_000_000,
    "liquid_net_worth_cents": 1_600_000_000,
}

INVESTOR_B = {
    "legal_name": "Bravo Holdings LLC",
    "entity_type": "LLC",
    "accreditation_method": "THIRD_PARTY_LETTER",
    "annual_income_cents": 250_000_000,
    "net_worth_cents": 1_500_000_000,
    "liquid_net_worth_cents": 1_000_000_000,
}

INVESTOR_C = {
    "legal_name": "Cedar Family Revocable Trust",
    "entity_type": "REVOCABLE_TRUST",
    "accreditation_method": "THIRD_PARTY_LETTER",
    "annual_income_cents": 60_000_000,
    "net_worth_cents": 800_000_000,
    "liquid_net_worth_cents": 400_000_000,
}

INVESTOR_E = {
    "legal_name": "Echo Ridge Partners",
    "entity_type": "INDIVIDUAL",
    "accreditation_method": "SELF_CERT_INCOME",
    "annual_income_cents": 60_000_000,
    "net_worth_cents": 500_000_000,
    "liquid_net_worth_cents": 200_000_000,
}

EXCHANGE_FILE_A = {
    "qi_reference": "QI-A-2026",
    "relinquished_closed_on": "2026-08-05",
    "relinquished_sale_price_cents": 400_000_000,
    "net_proceeds_cents": 250_000_000,
    "debt_retired_cents": 100_000_000,
    "identification_rule": "THREE_PROPERTY",
    "boot_tolerance_cents": 0,
}

EXCHANGE_FILE_B = {
    "qi_reference": "QI-B-2026",
    "relinquished_closed_on": "2026-08-10",
    "relinquished_sale_price_cents": 600_000_000,
    "net_proceeds_cents": 290_000_000,
    "debt_retired_cents": 120_000_000,
    "identification_rule": "TWO_HUNDRED_PCT",
    "boot_tolerance_cents": 0,
}

EXCHANGE_FILE_C = {
    "qi_reference": "QI-C-2026",
    "relinquished_closed_on": "2026-08-10",
    "relinquished_sale_price_cents": 20_000_000,
    "net_proceeds_cents": 12_000_000,
    "debt_retired_cents": 3_000_000,
    "identification_rule": "THREE_PROPERTY",
    "boot_tolerance_cents": 0,
}


def add_qualified_investor(
    deal: dict,
    key: str = "investor_a",
    investor_profile: dict = None,
    exchange_file: dict = None,
    evidence_reference: str = "NW-STMT-A-2026",
    approve_suitability: bool = True,
    suitability_headers=None,
    identify_property: bool = True,
) -> dict:
    """Onboard one investor, verify accreditation, approve suitability against
    the deal's offering, open its exchange file and identify the trust's
    property on it. Mutates and returns `deal`.
    """
    profile = dict(investor_profile or INVESTOR_A)
    investor = create_investor(**profile)
    investor = verify_accreditation(investor["id"], evidence_reference)
    if approve_suitability:
        investor = review_suitability(
            investor["id"], deal["offering"]["id"], "APPROVED", suitability_headers
        )
    deal[key] = investor

    file_spec = dict(exchange_file or EXCHANGE_FILE_A)
    xfile = create_exchange_file(investor["id"], **file_spec)
    deal[f"exchange_file_{key[-1]}"] = xfile
    if identify_property:
        deal[f"identification_{key[-1]}"] = file_identification(
            xfile["id"], deal["property"]["id"]
        )
        deal[f"exchange_file_{key[-1]}"] = read_exchange_file(xfile["id"])
    return deal


def setup_funding_with_investor_a(**overrides) -> dict:
    """FUNDING trust plus investor A verified, suitability APPROVED, exchange
    file IDENTIFIED against the trust's property."""
    deal = setup_trust_funding(**overrides)
    return add_qualified_investor(deal)


def setup_reserved_subscription_a(units_requested: int = 300, **overrides) -> dict:
    """FUNDING trust with one RESERVED subscription for investor A."""
    deal = setup_funding_with_investor_a(**overrides)
    deal["subscription_a"] = create_subscription(
        deal["offering"]["id"],
        deal["investor_a"]["id"],
        deal["exchange_file_a"]["id"],
        units_requested,
        deal["offering_version"],
    )
    return deal


# --------------------------------------------------------------------------
# Tier 4 — the completed raise: an OPERATING trust.
# --------------------------------------------------------------------------


def setup_operating_trust(**overrides) -> dict:
    """Two investors each close 300 of the 620 authorised units, which
    completes the raise and carries the trust FUNDING -> OPERATING.

    Leaves the clock at 2026-11-20 and returns the whole deal, including both
    closed subscriptions.
    """
    deal = setup_trust_funding_with_lease(**overrides)

    add_qualified_investor(
        deal,
        key="investor_a",
        investor_profile=INVESTOR_A,
        exchange_file=EXCHANGE_FILE_A,
        evidence_reference="NW-STMT-A-2026",
    )
    deal["subscription_a"] = create_subscription(
        deal["offering"]["id"],
        deal["investor_a"]["id"],
        deal["exchange_file_a"]["id"],
        300,
        deal["offering_version"],
    )

    # Investor B is onboarded but not yet verified: its accreditation is
    # verified only after A has closed, so B's ninety-day window still covers
    # its own closing.
    investor_b = create_investor(**INVESTOR_B)
    deal["investor_b"] = investor_b
    deal["exchange_file_b"] = create_exchange_file(investor_b["id"], **EXCHANGE_FILE_B)
    deal["identification_b"] = file_identification(
        deal["exchange_file_b"]["id"], deal["property"]["id"]
    )

    set_clock(CLOCK["SUB_A_CLOSE"])
    deal["subscription_a"] = close_subscription(deal["subscription_a"]["id"])

    set_clock(CLOCK["SUB_B_REVIEW"])
    deal["investor_b"] = verify_accreditation(investor_b["id"], "CPA-LTR-B-2026")
    deal["investor_b"] = review_suitability(
        investor_b["id"], deal["offering"]["id"], "APPROVED"
    )
    deal["subscription_b"] = create_subscription(
        deal["offering"]["id"],
        investor_b["id"],
        deal["exchange_file_b"]["id"],
        300,
        offering_version(deal["offering"]["id"]),
    )

    set_clock(CLOCK["SUB_B_CLOSE"])
    deal["subscription_b"] = close_subscription(deal["subscription_b"]["id"])

    deal["trust"] = read_trust(deal["trust"]["id"])
    deal["offering"] = read_offering(deal["offering"]["id"])
    return deal


def setup_raise_one_close_short(**overrides) -> dict:
    """The same deal one close short of completion: subscription A is CLOSED,
    subscription B is still RESERVED and the trust is still FUNDING. Clock at
    2026-11-20.
    """
    deal = setup_trust_funding_with_lease(**overrides)

    add_qualified_investor(
        deal,
        key="investor_a",
        investor_profile=INVESTOR_A,
        exchange_file=EXCHANGE_FILE_A,
        evidence_reference="NW-STMT-A-2026",
    )
    deal["subscription_a"] = create_subscription(
        deal["offering"]["id"],
        deal["investor_a"]["id"],
        deal["exchange_file_a"]["id"],
        300,
        deal["offering_version"],
    )

    investor_b = create_investor(**INVESTOR_B)
    deal["investor_b"] = investor_b
    deal["exchange_file_b"] = create_exchange_file(investor_b["id"], **EXCHANGE_FILE_B)
    deal["identification_b"] = file_identification(
        deal["exchange_file_b"]["id"], deal["property"]["id"]
    )

    set_clock(CLOCK["SUB_A_CLOSE"])
    deal["subscription_a"] = close_subscription(deal["subscription_a"]["id"])

    set_clock(CLOCK["SUB_B_REVIEW"])
    deal["investor_b"] = verify_accreditation(investor_b["id"], "CPA-LTR-B-2026")
    deal["investor_b"] = review_suitability(
        investor_b["id"], deal["offering"]["id"], "APPROVED"
    )
    deal["subscription_b"] = create_subscription(
        deal["offering"]["id"],
        investor_b["id"],
        deal["exchange_file_b"]["id"],
        300,
        offering_version(deal["offering"]["id"]),
    )

    set_clock(CLOCK["SUB_B_CLOSE"])
    deal["trust"] = read_trust(deal["trust"]["id"])
    return deal


def setup_operating_with_rent_and_debt(**overrides) -> dict:
    """OPERATING trust that has taken one quarter of cash through the books:
    base and supplemental rent on 2026-12-01 and one debt-service payment on
    2026-12-15. Leaves the clock at 2027-01-02, past the 2026-10-01/2027-01-01
    distribution period.
    """
    deal = setup_operating_trust(**overrides)
    set_clock(CLOCK["DECEMBER"])
    deal["rent_base_entry"] = post_rent(
        deal["trust"]["id"], rent_kind="BASE", amount_cents=22_500_000
    )
    deal["rent_supplemental_entry"] = post_rent(
        deal["trust"]["id"], rent_kind="SUPPLEMENTAL", amount_cents=375_000
    )
    set_clock(CLOCK["MID_DECEMBER"])
    deal["debt_service_entry"] = post_debt_service(
        deal["trust"]["id"], amount_cents=7_650_000
    )
    set_clock(CLOCK["NEW_YEAR"])
    deal["trust"] = read_trust(deal["trust"]["id"])
    return deal


def setup_declared_distribution(**overrides) -> dict:
    """OPERATING trust with the 2026-10-01 -> 2027-01-01 distribution DECLARED
    on the provisional accrual measurement."""
    deal = setup_operating_with_rent_and_debt(**overrides)
    deal["distribution"] = declare_distribution(
        deal["trust"]["id"], trust_version(deal["trust"]["id"])
    )
    return deal


def setup_paid_distribution(**overrides) -> dict:
    """OPERATING trust with that distribution PAID and its allocation rows
    written."""
    deal = setup_declared_distribution(**overrides)
    deal["distribution"] = pay_distribution(deal["distribution"]["id"])
    deal["allocations"] = list_allocations(deal["distribution"]["id"])
    deal["trust"] = read_trust(deal["trust"]["id"])
    return deal


# --------------------------------------------------------------------------
# Tier 4b — reserve pressure.
# --------------------------------------------------------------------------


def setup_reserve_draw_to_floor(**overrides) -> dict:
    """OPERATING trust whose reserve has been drawn to exactly its floor by a
    funded 25,000,000-cent repair, leaving the posture OPEN and one further
    cent of head-room short of the floor."""
    deal = setup_operating_trust(**overrides)
    deal["capital_need"] = create_capital_need(
        deal["trust"]["id"], amount_cents=25_000_000, needed_by="2026-12-31T00:00:00Z"
    )
    deal["capital_need"] = fund_capital_need(deal["capital_need"]["id"], "RESERVE")
    deal["reserve_draw_entry"] = find_ledger_entry(
        deal["trust"]["id"], "RESERVE_DRAW", "RESERVE"
    )
    deal["trust"] = read_trust(deal["trust"]["id"])
    return deal


# --------------------------------------------------------------------------
# Tier 5 — exit and liquidation.
# --------------------------------------------------------------------------


def setup_proposed_exit(exit_mode: str = "ASSET_SALE", **overrides) -> dict:
    """OPERATING trust with a PROPOSED exit event and no consents recorded.
    Clock at 2027-02-01."""
    exit_overrides = overrides.pop("exit_event", {})
    deal = setup_operating_trust(**overrides)
    set_clock(CLOCK["FEBRUARY"])
    deal["exit_event"] = create_exit_event(
        deal["trust"]["id"], exit_mode=exit_mode, **exit_overrides
    )
    return deal


def setup_approved_exit(exit_mode: str = "ASSET_SALE", **overrides) -> dict:
    """Both beneficial owners consent and the sponsor tallies, so the exit is
    APPROVED, the trust is WINDING_DOWN and its posture is FROZEN."""
    deal = setup_proposed_exit(exit_mode=exit_mode, **overrides)
    deal["consent_a"] = record_exit_consent(
        deal["exit_event"]["id"],
        deal["subscription_a"]["id"],
        deal["investor_a"]["id"],
        "CONSENT",
    )
    deal["consent_b"] = record_exit_consent(
        deal["exit_event"]["id"],
        deal["subscription_b"]["id"],
        deal["investor_b"]["id"],
        "CONSENT",
    )
    deal["exit_event"] = tally_consents(deal["exit_event"]["id"])
    deal["trust"] = read_trust(deal["trust"]["id"])
    return deal


def setup_closed_exit(exit_mode: str = "ASSET_SALE", **overrides) -> dict:
    """The full exit cascade has run: proceeds booked, reserve swept, property
    DISPOSED, liquidating distribution declared and one successor exchange file
    seeded per closed subscription. Clock at 2027-03-01."""
    deal = setup_approved_exit(exit_mode=exit_mode, **overrides)
    set_clock(CLOCK["MARCH"])
    deal["exit_event"] = close_exit_event(deal["exit_event"]["id"])
    deal["trust"] = read_trust(deal["trust"]["id"])
    deal["successor_files"] = list_exchange_files_for_exit(deal["exit_event"]["id"])
    return deal


# --------------------------------------------------------------------------
# Tier 5b — exchange-file-only scenarios, where no trust is needed.
# --------------------------------------------------------------------------


def setup_exchange_file_only(**overrides) -> dict:
    """Clock at 2026-08-20, one investor and one OPEN exchange file."""
    set_clock(CLOCK["PRE_ACQUISITION"])
    investor = create_investor(**INVESTOR_A)
    spec = dict(EXCHANGE_FILE_A)
    spec.update(overrides)
    xfile = create_exchange_file(investor["id"], **spec)
    return {"investor": investor, "exchange_file": xfile}


def setup_identified_exchange_file(**overrides) -> dict:
    """Clock at 2026-08-20, one property, one investor, one exchange file with
    a single ACTIVE identification, so the file is IDENTIFIED."""
    set_clock(CLOCK["PRE_ACQUISITION"])
    prop = create_property()
    investor = create_investor(**INVESTOR_A)
    spec = dict(EXCHANGE_FILE_A)
    spec.update(overrides)
    xfile = create_exchange_file(investor["id"], **spec)
    identification = file_identification(xfile["id"], prop["id"])
    return {
        "property": prop,
        "investor": investor,
        "exchange_file": read_exchange_file(xfile["id"]),
        "identification": identification,
    }


def setup_open_exchange_file_at_deadline(**overrides) -> dict:
    """One OPEN exchange file, one property, and the clock wound to exactly the
    file's identification deadline instant."""
    set_clock(CLOCK["START"])
    prop = create_property()
    investor = create_investor(**INVESTOR_A)
    spec = dict(EXCHANGE_FILE_A)
    spec.update(overrides)
    xfile = create_exchange_file(investor["id"], **spec)
    set_clock(xfile["identification_deadline"])
    return {"property": prop, "investor": investor, "exchange_file": xfile}
