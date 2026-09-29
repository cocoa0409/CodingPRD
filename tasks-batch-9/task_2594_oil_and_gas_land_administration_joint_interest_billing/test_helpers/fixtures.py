"""Composite setup helpers that build multi-step preconditions from scratch.

Every helper here drives only endpoints the requirements declare, in the
order the requirements permit, and returns the identifiers and payloads a
test needs to make its assertions.  Nothing is seeded directly into
storage: the service under test is the only way state comes into being.

The database is empty at the start of every test, so each helper sets the
logical clock first and then walks forward through the land, well,
ownership, and billing layers.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories
from test_helpers.api_client import ApiClient, api_client
from test_helpers.test_users import (
    TEST_USERS,
    make_partner_representative_headers,
)

# The clock value most composite setups start from.  It sits on or after
# the service's own start instant of 2026-08-01T00:00:00Z (the clock only
# ever moves forward), after the June billing period the cost fixtures
# use, and before the September primary-term deadline, so leases are
# still inside their primary term.
CLOCK_DEFAULT = "2026-08-10T00:00:00Z"

# A later start used by setups that reason about August notices and
# shut-in obligations.
CLOCK_AUGUST = "2026-08-05T00:00:00Z"

LAND_ADMIN = TEST_USERS["land_administrator_headers"]
JIB_ACCOUNTANT = TEST_USERS["joint_interest_accountant_headers"]
AUDIT_REVIEWER = TEST_USERS["audit_reviewer_headers"]
SECOND_AUDIT_REVIEWER = TEST_USERS["second_audit_reviewer_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]

# ---------------------------------------------------------------------------
# Canonical land and well descriptions
# ---------------------------------------------------------------------------

# 640 acres at a 3/16 royalty, primary term ending 2026-09-30.
LEASE_ONE = {
    "lease_number": "L-001",
    "lessor_name": "Alpha Minerals",
    "gross_acres": 640.00,
    "royalty_rate": 0.1875,
    "primary_term_end_date": "2026-09-30",
    "extension_option_months": 24,
    "extension_bonus_per_acre_cents": 15000,
    "shut_in_royalty_per_acre_cents": 500,
    "continuous_dev_window_days": 180,
}

# 320 acres at a 1/4 royalty, primary term running well past the window
# the tests exercise, so it can act as the surviving tract.
LEASE_TWO = {
    "lease_number": "L-002",
    "lessor_name": "Beta Royalties",
    "gross_acres": 320.00,
    "royalty_rate": 0.25,
    "primary_term_end_date": "2027-12-31",
    "extension_option_months": 12,
    "extension_bonus_per_acre_cents": 12000,
    "shut_in_royalty_per_acre_cents": 400,
    "continuous_dev_window_days": 180,
}

# An oil well at 9,500 feet of total depth.
WELL_ONE = {
    "well_name": "Sandstone 1H",
    "api_number": "42-123-45678",
    "product_type": "OIL",
    "total_depth_ft": 9500,
    "spud_date": "2026-02-10",
}

OPERATOR_OWNER = {
    "owner_name": "Operator Energy LLC",
    "owner_type": "WORKING_INTEREST_PARTNER",
    "contact_email": "op@example.com",
    "tax_id_on_file": True,
    "bond_posted_cents": 50_000_000,
}

PARTNER_A_OWNER = {
    "owner_name": "Delta Partners LP",
    "owner_type": "WORKING_INTEREST_PARTNER",
    "contact_email": "delta@example.com",
    "tax_id_on_file": True,
    "bond_posted_cents": 10_000_000,
}

PARTNER_B_OWNER = {
    "owner_name": "Epsilon Resources Inc",
    "owner_type": "WORKING_INTEREST_PARTNER",
    "contact_email": "epsilon@example.com",
    "tax_id_on_file": True,
    "bond_posted_cents": 0,
}

# A registered partner that holds no interest in the well; it exists so a
# conveyance has somewhere to go.
PARTNER_C_OWNER = {
    "owner_name": "Gamma Operating LP",
    "owner_type": "WORKING_INTEREST_PARTNER",
    "contact_email": "gamma@example.com",
    "tax_id_on_file": True,
    "bond_posted_cents": 20_000_000,
}


# ---------------------------------------------------------------------------
# Single-step primitives
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> dict:
    """Move the logical clock forward to an explicit instant."""
    return get_success_data(
        api.set_current_utc(factories.set_clock_payload(current_utc), LAND_ADMIN)
    )


def create_lease(api: ApiClient, **overrides) -> dict:
    payload = dict(LEASE_ONE)
    payload.update(overrides)
    return get_success_data(api.create_lease(payload, LAND_ADMIN))


def create_well(api: ApiClient, **overrides) -> dict:
    payload = dict(WELL_ONE)
    payload.update(overrides)
    return get_success_data(api.create_well(payload, LAND_ADMIN))


def create_owner(api: ApiClient, template: dict, **overrides) -> dict:
    payload = dict(template)
    payload.update(overrides)
    return get_success_data(api.create_interest_owner(payload, LAND_ADMIN))


def commit_acreage(
    api: ApiClient, well_id: str, lease_id: str, committed_acres: float
) -> dict:
    return get_success_data(
        api.create_lease_allocation(
            well_id,
            factories.lease_allocation_payload(lease_id, committed_acres),
            LAND_ADMIN,
        )
    )


def well_version(api: ApiClient, well_id: str) -> int:
    """Read back the well's current version so an interest write can pin it."""
    return get_success_data(api.get_well(well_id, LAND_ADMIN))["version"]


def add_interest(
    api: ApiClient,
    well_id: str,
    owner_id: str,
    working_interest_pct: float,
    net_revenue_interest_pct: float,
    effective_from: str = "2026-01-01",
    **overrides,
) -> dict:
    """Record one working-interest row, pinning the well version first.

    Recording an interest is version-pinned, and each accepted write bumps
    the well, so the current version is re-read immediately before the call.
    """
    payload = factories.create_well_interest_payload(
        owner_id=owner_id,
        working_interest_pct=working_interest_pct,
        net_revenue_interest_pct=net_revenue_interest_pct,
        effective_from=effective_from,
        expected_well_version=well_version(api, well_id),
        **overrides,
    )
    return get_success_data(api.create_well_interest(well_id, payload, LAND_ADMIN))


def effectuate_pooling(api: ApiClient, well_id: str, effective_date: str) -> dict:
    return get_success_data(
        api.effectuate_pooling(
            well_id, factories.pooling_effectuation_payload(effective_date), LAND_ADMIN
        )
    )


def change_status(
    api: ApiClient, well_id: str, to_status: str, effective_date: str, **overrides
) -> dict:
    payload = factories.well_status_change_payload(
        to_status, effective_date=effective_date, **overrides
    )
    return get_success_data(api.change_well_status(well_id, payload, LAND_ADMIN))


def book_cost(
    api: ApiClient,
    well_id: str,
    cost_category: str,
    cost_class: str,
    amount_cents: int,
    incurred_date: str,
    paid_date: str = None,
    **overrides,
) -> dict:
    payload = factories.create_cost_entry_payload(
        cost_category=cost_category,
        cost_class=cost_class,
        amount_cents=amount_cents,
        incurred_date=incurred_date,
        **overrides,
    )
    if paid_date is not None:
        payload["paid_date"] = paid_date
    return get_success_data(api.create_cost_entry(well_id, payload, JIB_ACCOUNTANT))


def open_statement(api: ApiClient, well_id: str, **overrides) -> dict:
    payload = factories.create_jib_statement_payload(**overrides)
    return get_success_data(api.create_jib_statement(well_id, payload, JIB_ACCOUNTANT))


def issue_statement(api: ApiClient, statement_id: str) -> dict:
    return get_success_data(api.issue_jib_statement(statement_id, JIB_ACCOUNTANT))


def get_line_items(api: ApiClient, statement_id: str) -> list:
    return get_success_data(
        api.list_jib_statement_line_items(
            statement_id, JIB_ACCOUNTANT, params={"limit": 100}
        )
    )


def line_item_for(api: ApiClient, statement_id: str, owner_id: str) -> dict:
    """Return the single charge row a statement carries for one owner."""
    rows = [
        row for row in get_line_items(api, statement_id) if row["owner_id"] == owner_id
    ]
    assert len(rows) == 1, (
        f"expected exactly one charge row for owner {owner_id} on statement "
        f"{statement_id}, found {len(rows)}"
    )
    return rows[0]


def book_revenue(
    api: ApiClient,
    well_id: str,
    production_month: str,
    gross_revenue_cents: int,
    volume_units: float,
    sale_date: str,
) -> dict:
    payload = factories.create_production_revenue_payload(
        production_month=production_month,
        gross_revenue_cents=gross_revenue_cents,
        volume_units=volume_units,
        sale_date=sale_date,
    )
    return get_success_data(
        api.create_production_revenue(well_id, payload, JIB_ACCOUNTANT)
    )


def release_revenue(api: ApiClient, revenue_id: str) -> dict:
    return get_success_data(api.release_production_revenue(revenue_id, JIB_ACCOUNTANT))


def disbursements_for(api: ApiClient, revenue_id: str, **params) -> list:
    query = {"revenue_id": revenue_id, "limit": 100}
    query.update(params)
    return get_success_data(api.list_owner_disbursements(JIB_ACCOUNTANT, params=query))


def one_disbursement(api: ApiClient, revenue_id: str, owner_id: str, lease_id: str) -> dict:
    rows = disbursements_for(
        api, revenue_id, owner_id=owner_id, lease_id=lease_id
    )
    assert len(rows) == 1, (
        f"expected exactly one payment row for owner {owner_id} on tract "
        f"{lease_id}, found {len(rows)}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2 - the shared land, well and ownership foundation
# ---------------------------------------------------------------------------


def setup_pooled_producing_well(
    api: ApiClient = api_client,
    clock: str = CLOCK_DEFAULT,
    include_fourth_owner: bool = True,
    owner_b_tax_id_on_file: bool = True,
    produce: bool = True,
) -> dict:
    """Build the standard drilling unit every billing test starts from.

    Two tracts are recorded, a well is drilled across them, four partners
    are registered, three of them take working interest that sums to one,
    the unit is pooled, and the well is walked from PROPOSED through
    DRILLING to PRODUCING.

    The 480/160 acre commitment out of 640 and 320 gross acres gives the
    unit allocation factors of 0.750000 and 0.250000.  Working interest is
    50/30/20 with net revenue interest 0.4125/0.24/0.15, so the operator
    and the first partner both carry a preferential right and the second
    partner does not.

    ``include_fourth_owner`` registers a partner that takes no interest, so
    a conveyance has a stranger to convey to.  ``owner_b_tax_id_on_file``
    lets a caller start the second partner out of compliance.
    ``produce=False`` leaves the well in DRILLING.
    """
    set_clock(api, clock)

    lease1 = create_lease(api, **LEASE_ONE)
    lease2 = create_lease(api, **LEASE_TWO)
    well = create_well(api)

    alloc1 = commit_acreage(api, well["id"], lease1["id"], 480.00)
    alloc2 = commit_acreage(api, well["id"], lease2["id"], 160.00)

    operator = create_owner(api, OPERATOR_OWNER)
    partner_a = create_owner(api, PARTNER_A_OWNER)
    partner_b = create_owner(
        api, PARTNER_B_OWNER, tax_id_on_file=owner_b_tax_id_on_file
    )
    partner_c = create_owner(api, PARTNER_C_OWNER) if include_fourth_owner else None

    wi_operator = add_interest(
        api,
        well["id"],
        operator["id"],
        working_interest_pct=0.5,
        net_revenue_interest_pct=0.4125,
        is_operator=True,
        preferential_right=True,
    )
    wi_partner_a = add_interest(
        api,
        well["id"],
        partner_a["id"],
        working_interest_pct=0.3,
        net_revenue_interest_pct=0.24,
        is_operator=False,
        preferential_right=True,
    )
    wi_partner_b = add_interest(
        api,
        well["id"],
        partner_b["id"],
        working_interest_pct=0.2,
        net_revenue_interest_pct=0.15,
        is_operator=False,
        preferential_right=False,
    )

    effectuate_pooling(api, well["id"], "2026-04-01")
    change_status(api, well["id"], "DRILLING", "2026-02-10")
    if produce:
        change_status(api, well["id"], "PRODUCING", "2026-04-01")

    context = {
        "clock": clock,
        "lease1": lease1,
        "lease2": lease2,
        "lease1_id": lease1["id"],
        "lease2_id": lease2["id"],
        "well_id": well["id"],
        "alloc1": alloc1,
        "alloc2": alloc2,
        "alloc1_id": alloc1["id"],
        "alloc2_id": alloc2["id"],
        "operator": operator,
        "partner_a": partner_a,
        "partner_b": partner_b,
        "partner_c": partner_c,
        "operator_id": operator["id"],
        "partner_a_id": partner_a["id"],
        "partner_b_id": partner_b["id"],
        "partner_c_id": partner_c["id"] if partner_c else None,
        "wi_operator": wi_operator,
        "wi_partner_a": wi_partner_a,
        "wi_partner_b": wi_partner_b,
        "wi_operator_id": wi_operator["id"],
        "wi_partner_a_id": wi_partner_a["id"],
        "wi_partner_b_id": wi_partner_b["id"],
        "operator_headers": make_partner_representative_headers(operator["id"]),
        "partner_a_headers": make_partner_representative_headers(partner_a["id"]),
        "partner_b_headers": make_partner_representative_headers(partner_b["id"]),
        "partner_c_headers": (
            make_partner_representative_headers(partner_c["id"]) if partner_c else None
        ),
    }
    # Re-read the well so callers see the version and computed rollups that
    # the pooling and status writes left behind.
    context["well"] = get_success_data(api.get_well(well["id"], LAND_ADMIN))
    return context


# ---------------------------------------------------------------------------
# Tier 3 - cost history and statement shortcuts
# ---------------------------------------------------------------------------


def book_june_cost_history(api: ApiClient, well_id: str) -> list:
    """Book the three June costs the standard statement is drawn from.

    Two capital charges of 2,000,000 and 500,000 cents plus one operating
    charge of 300,000 cents, all incurred and paid inside June 2026.
    """
    return [
        book_cost(
            api, well_id, "COMPLETION", "CAPITAL", 2_000_000, "2026-06-05", "2026-06-06"
        ),
        book_cost(
            api, well_id, "COMPLETION", "CAPITAL", 500_000, "2026-06-07", "2026-06-08"
        ),
        book_cost(
            api,
            well_id,
            "LEASE_OPERATING",
            "OPERATING",
            300_000,
            "2026-06-09",
            "2026-06-10",
        ),
    ]


def book_residual_cost_history(api: ApiClient, well_id: str) -> list:
    """Book a June cost pair whose owner splits do not divide evenly.

    1,000,005 cents of capital and 100,003 cents of operating charges, so
    every allocated bucket needs rounding and a residual has to land
    somewhere.
    """
    return [
        book_cost(
            api, well_id, "COMPLETION", "CAPITAL", 1_000_005, "2026-06-05", "2026-06-06"
        ),
        book_cost(
            api,
            well_id,
            "LEASE_OPERATING",
            "OPERATING",
            100_003,
            "2026-06-07",
            "2026-06-08",
        ),
    ]


def setup_residual_statement(
    api: ApiClient = api_client, clock: str = CLOCK_DEFAULT, **well_kwargs
) -> dict:
    """A pooled producing well with a June draft over the residual costs.

    Direct charges total 1,100,008 cents and overhead adds 53,000, so the
    draft carries 1,153,008 cents across three owners.
    """
    context = setup_pooled_producing_well(api, clock=clock, **well_kwargs)
    context["costs"] = book_residual_cost_history(api, context["well_id"])
    statement = open_statement(api, context["well_id"])
    context["statement"] = statement
    context["statement_id"] = statement["id"]
    return context


def setup_issued_residual_statement(
    api: ApiClient = api_client, clock: str = CLOCK_DEFAULT, **well_kwargs
) -> dict:
    """The residual June draft, issued so it sits on the billed ledger."""
    context = setup_residual_statement(api, clock=clock, **well_kwargs)
    context["statement"] = issue_statement(api, context["statement_id"])
    return context


def setup_standard_june_statement(
    api: ApiClient = api_client, clock: str = CLOCK_DEFAULT, **well_kwargs
) -> dict:
    """A pooled producing well with a June draft over the standard costs.

    Direct charges total 2,800,000 cents and percentage-basis overhead adds
    134,000, so the draft carries 2,934,000 cents.
    """
    context = setup_pooled_producing_well(api, clock=clock, **well_kwargs)
    context["costs"] = book_june_cost_history(api, context["well_id"])
    statement = open_statement(api, context["well_id"])
    context["statement"] = statement
    context["statement_id"] = statement["id"]
    return context


def setup_issued_june_statement(
    api: ApiClient = api_client, clock: str = CLOCK_DEFAULT, **well_kwargs
) -> dict:
    """The standard June draft, issued."""
    context = setup_standard_june_statement(api, clock=clock, **well_kwargs)
    context["statement"] = issue_statement(api, context["statement_id"])
    return context


def setup_disputed_statement(
    api: ApiClient = api_client,
    clock: str = CLOCK_DEFAULT,
    disputed_amount_cents: int = 100_000,
    dispute_kind: str = "BILLING_DISPUTE",
    basis_note: str = "Capital pool includes a non-joint cost",
    **well_kwargs,
) -> dict:
    """An issued residual statement contested by the second partner."""
    context = setup_issued_residual_statement(api, clock=clock, **well_kwargs)
    dispute = get_success_data(
        api.file_dispute(
            context["statement_id"],
            factories.file_dispute_payload(
                owner_id=context["partner_b_id"],
                disputed_amount_cents=disputed_amount_cents,
                dispute_kind=dispute_kind,
                basis_note=basis_note,
            ),
            context["partner_b_headers"],
        )
    )
    context["dispute"] = dispute
    context["dispute_id"] = dispute["id"]
    context["statement"] = get_success_data(
        api.get_jib_statement(context["statement_id"], JIB_ACCOUNTANT)
    )
    return context


def setup_responded_dispute(
    api: ApiClient = api_client,
    clock: str = CLOCK_DEFAULT,
    exchange_note: str = "Cost is joint per the operating agreement, exhibit C",
    **kwargs,
) -> dict:
    """A contested statement the operator has already answered once."""
    context = setup_disputed_statement(api, clock=clock, **kwargs)
    context["operator_response"] = get_success_data(
        api.create_dispute_exchange(
            context["dispute_id"],
            factories.dispute_exchange_payload("OPERATOR_RESPONSE", exchange_note),
            JIB_ACCOUNTANT,
        )
    )
    context["dispute"] = get_success_data(
        api.get_dispute(context["dispute_id"], JIB_ACCOUNTANT)
    )
    return context


# ---------------------------------------------------------------------------
# Tier 4 - authorisations, elections and non-consent
# ---------------------------------------------------------------------------


def raise_afe(api: ApiClient, well_id: str, **overrides) -> dict:
    """Circulate one authorization for expenditure against the well."""
    payload = factories.create_afe_payload(**overrides)
    return get_success_data(api.create_afe(well_id, payload, LAND_ADMIN))


def submit_election(
    api: ApiClient, afe_id: str, owner_id: str, election_type: str, headers=None
) -> dict:
    return get_success_data(
        api.submit_afe_election(
            afe_id,
            factories.afe_election_payload(owner_id, election_type),
            headers or LAND_ADMIN,
        )
    )


def close_elections(api: ApiClient, afe_id: str) -> dict:
    return get_success_data(
        api.close_afe_elections(afe_id, factories.election_closure_payload(), LAND_ADMIN)
    )


def setup_closed_non_consent_afe(
    api: ApiClient = api_client,
    clock: str = CLOCK_DEFAULT,
    afe_number: str = "AFE-001",
    operation_type: str = "COMPLETION",
    **well_kwargs,
) -> dict:
    """A pooled well whose completion authorization has closed with a refusal.

    The first partner consents, the second refuses, and the operator never
    answers, so closure has to decide what the operator's silence means.
    """
    context = setup_pooled_producing_well(api, clock=clock, **well_kwargs)
    afe = raise_afe(
        api,
        context["well_id"],
        afe_number=afe_number,
        operation_type=operation_type,
        estimated_cost_cents=2_000_000,
        cost_class="CAPITAL",
        election_deadline_date="2026-08-31",
        non_consent_penalty_multiple=3.0,
        minimum_consent_pct=0.5,
    )
    submit_election(api, afe["id"], context["partner_a_id"], "CONSENT")
    submit_election(api, afe["id"], context["partner_b_id"], "NON_CONSENT")
    context["afe"] = close_elections(api, afe["id"])
    context["afe_id"] = afe["id"]
    return context


def setup_non_consent_statement(
    api: ApiClient = api_client, clock: str = CLOCK_DEFAULT, **well_kwargs
) -> dict:
    """A June draft drawn over a mix of authorized and routine charges.

    2,000,000 cents of capital tied to the closed authorization, 500,000
    cents of capital that is not, and 300,000 cents of operating charges,
    so the refusing partner is carried on part of the pool only.
    """
    context = setup_closed_non_consent_afe(api, clock=clock, **well_kwargs)
    well_id = context["well_id"]
    context["costs"] = [
        book_cost(
            api,
            well_id,
            "COMPLETION",
            "CAPITAL",
            2_000_000,
            "2026-06-05",
            "2026-06-06",
            afe_id=context["afe_id"],
        ),
        book_cost(
            api, well_id, "COMPLETION", "CAPITAL", 500_000, "2026-06-07", "2026-06-08"
        ),
        book_cost(
            api,
            well_id,
            "LEASE_OPERATING",
            "OPERATING",
            300_000,
            "2026-06-09",
            "2026-06-10",
        ),
    ]
    statement = open_statement(api, well_id)
    context["statement"] = statement
    context["statement_id"] = statement["id"]
    return context


def setup_issued_non_consent_statement(
    api: ApiClient = api_client, clock: str = CLOCK_DEFAULT, **well_kwargs
) -> dict:
    """The non-consent June draft, issued onto the billed ledger."""
    context = setup_non_consent_statement(api, clock=clock, **well_kwargs)
    context["statement"] = issue_statement(api, context["statement_id"])
    return context


# ---------------------------------------------------------------------------
# Tier 4 - revenue, royalty and payment rows
# ---------------------------------------------------------------------------


def setup_released_revenue_month(
    api: ApiClient = api_client,
    clock: str = CLOCK_DEFAULT,
    production_month: str = "2026-06",
    gross_revenue_cents: int = 3_000_000,
    volume_units: float = 3750.0,
    sale_date: str = "2026-07-05",
    **well_kwargs,
) -> dict:
    """A pooled producing well with one month of revenue released to owners."""
    context = setup_pooled_producing_well(api, clock=clock, **well_kwargs)
    revenue = book_revenue(
        api,
        context["well_id"],
        production_month,
        gross_revenue_cents,
        volume_units,
        sale_date,
    )
    context["revenue"] = release_revenue(api, revenue["id"])
    context["revenue_id"] = revenue["id"]
    context["disbursements"] = disbursements_for(api, revenue["id"])
    return context


def setup_two_released_revenue_months(
    api: ApiClient = api_client, clock: str = CLOCK_AUGUST
) -> dict:
    """Two revenue months whose sale dates straddle the statutory deadline.

    June sells on 2026-07-05 and July sells on 2026-08-04.  Both months
    carry 5,000,000 cents of gross revenue on 6,250 units, so the two
    payment rows differ only in when the money arrived.
    """
    context = setup_pooled_producing_well(
        api, clock=clock, include_fourth_owner=False
    )
    june = book_revenue(
        api, context["well_id"], "2026-06", 5_000_000, 6250.0, "2026-07-05"
    )
    context["june_revenue"] = release_revenue(api, june["id"])
    context["june_revenue_id"] = june["id"]
    july = book_revenue(
        api, context["well_id"], "2026-07", 5_000_000, 6250.0, "2026-08-04"
    )
    context["july_revenue"] = release_revenue(api, july["id"])
    context["july_revenue_id"] = july["id"]
    context["june_disbursement"] = one_disbursement(
        api, june["id"], context["operator_id"], context["lease1_id"]
    )
    context["july_disbursement"] = one_disbursement(
        api, july["id"], context["operator_id"], context["lease1_id"]
    )
    return context


# ---------------------------------------------------------------------------
# Tier 5 - conveyance notices
# ---------------------------------------------------------------------------


def setup_assignment_notice(
    api: ApiClient = api_client,
    clock: str = CLOCK_AUGUST,
    assignor: str = "operator_id",
    assignee: str = "partner_c_id",
    transfer_wi_pct: float = 0.1,
    transfer_nri_pct: float = 0.08,
    sale_price_cents: int = 4_000_000,
    notice_date: str = "2026-08-01",
    effective_date: str = "2026-08-05",
    context: dict = None,
    **well_kwargs,
) -> dict:
    """Notice a conveyance of working interest out of the pooled well."""
    if context is None:
        context = setup_pooled_producing_well(api, clock=clock, **well_kwargs)
    transfer = get_success_data(
        api.create_assignment_transfer(
            context["well_id"],
            factories.create_assignment_transfer_payload(
                assignor_owner_id=context[assignor],
                assignee_owner_id=context[assignee],
                transfer_wi_pct=transfer_wi_pct,
                transfer_nri_pct=transfer_nri_pct,
                sale_price_cents=sale_price_cents,
                notice_date=notice_date,
                effective_date=effective_date,
            ),
            LAND_ADMIN,
        )
    )
    context["transfer"] = transfer
    context["transfer_id"] = transfer["id"]
    return context


def submit_ppr(api: ApiClient, transfer_id: str, headers, election: str) -> dict:
    return get_success_data(
        api.submit_ppr_election(
            transfer_id, factories.ppr_election_payload(election), headers
        )
    )


def close_transfer(api: ApiClient, transfer_id: str, closing_date: str) -> dict:
    return get_success_data(
        api.close_assignment_transfer(
            transfer_id, factories.transfer_closing_payload(closing_date), LAND_ADMIN
        )
    )


def run_obligation_pass(api: ApiClient) -> dict:
    """Sweep every lease for tenure and obligation deadlines that have passed."""
    return get_success_data(api.run_obligation_pass(COMPLIANCE_OFFICER))


def active_interests(api: ApiClient, well_id: str) -> list:
    rows = get_success_data(
        api.list_well_interests(
            LAND_ADMIN, params={"well_id": well_id, "limit": 100}
        )
    )
    return [row for row in rows if row["interest_status"] == "ACTIVE"]
