"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient `get_success_data` validator so a broken
precondition surfaces as a clear "Setup step failed" rather than as a confusing
assertion inside the test body.

Identity threading: a `ConcessionaireOperator` presents the acting
`Concessionaire.id` as `X-User-ID`, so every ownership-gated call below is made
with `make_operator_headers(concessionaire["id"])`.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    ADMIN,
    AUDITOR,
    AUDITOR_2,
    TREASURY,
    make_operator_headers,
)


# ---------------------------------------------------------------------------
# Tier 0 — single-resource primitives
# ---------------------------------------------------------------------------

def create_facility(api=None, **overrides) -> dict:
    api = api or api_client
    return get_success_data(api.create_facility(f.facility_payload(**overrides), ADMIN))


def create_concessionaire(api, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_concessionaire(f.concessionaire_payload(facility_id, **overrides), ADMIN)
    )


def create_agreement(api, facility_id: str, concessionaire_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_agreement(
            f.agreement_payload(facility_id, concessionaire_id, **overrides), ADMIN
        )
    )


def execute_agreement(api, agreement_id: str) -> dict:
    return get_success_data(api.execute_agreement(agreement_id, ADMIN))


def create_counter_space(api, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_counter_space(f.counter_space_payload(facility_id, **overrides), ADMIN)
    )


def create_fleet_zone(api, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_fleet_zone(f.fleet_zone_payload(facility_id, **overrides), ADMIN)
    )


def create_obligation(api, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_obligation(f.obligation_payload(facility_id, **overrides), ADMIN)
    )


def create_project(api, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_project(f.project_payload(facility_id, **overrides), ADMIN)
    )


def approve_project(api, project_id: str) -> dict:
    return get_success_data(api.approve_project(project_id, ADMIN))


def create_shuttle_period(api, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_shuttle_period(f.shuttle_period_payload(facility_id, **overrides), TREASURY)
    )


def create_settlement(api, agreement_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_settlement(
            f.settlement_payload(agreement_id, **overrides), headers or AUDITOR_2
        )
    )


def read_agreement_version(api, agreement_id: str, headers=None) -> int:
    return get_success_data(api.get_agreement(agreement_id, headers or ADMIN))["version"]


def read_zone_version(api, zone_id: str, headers=None) -> int:
    return get_success_data(api.get_fleet_zone(zone_id, headers or ADMIN))["version"]


def read_project_version(api, project_id: str, headers=None) -> int:
    return get_success_data(api.get_project(project_id, headers or ADMIN))["version"]


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------

def setup_active_agreement(
    api,
    facility_overrides=None,
    concessionaire_overrides=None,
    agreement_overrides=None,
) -> dict:
    """One facility, one registered brand, one agreement executed to ACTIVE.

    Returns {"facility", "concessionaire", "agreement", "operator"} where
    "operator" is the ConcessionaireOperator header dict bound to that brand.
    """
    facility = create_facility(api, **(facility_overrides or {}))
    concessionaire = create_concessionaire(
        api, facility["id"], **(concessionaire_overrides or {})
    )
    agreement = create_agreement(
        api, facility["id"], concessionaire["id"], **(agreement_overrides or {})
    )
    agreement = execute_agreement(api, agreement["id"])
    return {
        "facility": facility,
        "concessionaire": concessionaire,
        "agreement": agreement,
        "operator": make_operator_headers(concessionaire["id"]),
    }


def add_brand_with_active_agreement(
    api, facility_id: str, brand_code: str, legal_name: str, **agreement_overrides
) -> dict:
    """Register another brand at an existing facility and execute its agreement."""
    concessionaire = create_concessionaire(
        api,
        facility_id,
        legal_name=legal_name,
        brand_code=brand_code,
        contact_email=f"{brand_code.lower()}@x.example",
    )
    agreement = create_agreement(
        api, facility_id, concessionaire["id"], **agreement_overrides
    )
    agreement = execute_agreement(api, agreement["id"])
    return {
        "concessionaire": concessionaire,
        "agreement": agreement,
        "operator": make_operator_headers(concessionaire["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2 — transaction-day report lifecycle
# ---------------------------------------------------------------------------

def create_report(api, agreement_id: str, operator_headers: dict, **overrides) -> dict:
    return get_success_data(
        api.create_report(f.report_payload(agreement_id, **overrides), operator_headers)
    )


def submit_report(api, report_id: str, operator_headers: dict) -> dict:
    return get_success_data(api.submit_report(report_id, operator_headers))


def begin_audit(api, report_id: str, auditor_headers=None) -> dict:
    return get_success_data(api.begin_audit_report(report_id, auditor_headers or AUDITOR))


def accept_report(api, report_id: str, auditor_headers=None, **accept_overrides) -> dict:
    return get_success_data(
        api.accept_report(
            report_id, f.accept_report_payload(**accept_overrides), auditor_headers or AUDITOR
        )
    )


def reject_report(api, report_id: str, auditor_headers=None, **reject_overrides) -> dict:
    return get_success_data(
        api.reject_report(
            report_id, f.reject_report_payload(**reject_overrides), auditor_headers or AUDITOR
        )
    )


def reopen_report(api, report_id: str, operator_headers: dict) -> dict:
    return get_success_data(api.reopen_report(report_id, operator_headers))


def create_report_under_audit(
    api, agreement_id: str, operator_headers: dict, auditor_headers=None, **overrides
) -> dict:
    """Draft -> submit -> begin-audit.  Leaves the report in UNDER_AUDIT."""
    report = create_report(api, agreement_id, operator_headers, **overrides)
    submit_report(api, report["id"], operator_headers)
    return begin_audit(api, report["id"], auditor_headers)


def create_accepted_report(
    api,
    agreement_id: str,
    operator_headers: dict,
    auditor_headers=None,
    audited_gross_revenue_cents=None,
    audited_on_airport_transaction_days=None,
    **overrides,
) -> dict:
    """Draft -> submit -> begin-audit -> accept.

    The audited figures default to the reported ones, so the report is accepted
    with zero revenue variance unless the caller asks otherwise.
    """
    report = create_report(api, agreement_id, operator_headers, **overrides)
    submit_report(api, report["id"], operator_headers)
    begin_audit(api, report["id"], auditor_headers)
    audited_rev = (
        report["reported_gross_revenue_cents"]
        if audited_gross_revenue_cents is None
        else audited_gross_revenue_cents
    )
    audited_days = (
        report["reported_on_airport_transaction_days"]
        if audited_on_airport_transaction_days is None
        else audited_on_airport_transaction_days
    )
    return accept_report(
        api,
        report["id"],
        auditor_headers,
        audited_gross_revenue_cents=audited_rev,
        audited_on_airport_transaction_days=audited_days,
    )


# ---------------------------------------------------------------------------
# Tier 2 — remittances
# ---------------------------------------------------------------------------

def create_remittance(
    api, agreement_id: str, report_id: str, operator_headers: dict, remittance_basis="FINAL"
) -> dict:
    return get_success_data(
        api.create_remittance(
            f.remittance_payload(agreement_id, report_id, remittance_basis=remittance_basis),
            operator_headers,
        )
    )


def receive_cash(api, remittance_id: str, amount_received_cents: int, headers=None) -> dict:
    return get_success_data(
        api.receive_remittance(
            remittance_id, f.receive_payload(amount_received_cents), headers or TREASURY
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — space bookings (both carry a mandatory parent version)
# ---------------------------------------------------------------------------

def create_counter_assignment(
    api, agreement_id: str, counter_space_id: str, operator_headers: dict, **overrides
) -> dict:
    """Reads the agreement's live version so the create is never stale."""
    version = read_agreement_version(api, agreement_id, operator_headers)
    payload = f.counter_assignment_payload(
        agreement_id, counter_space_id, version, **overrides
    )
    return get_success_data(api.create_counter_assignment(payload, operator_headers))


def create_fleet_allocation(
    api, agreement_id: str, zone_id: str, operator_headers: dict, **overrides
) -> dict:
    """Reads the zone's live version so the create is never stale."""
    version = read_zone_version(api, zone_id, operator_headers)
    payload = f.fleet_allocation_payload(agreement_id, zone_id, version, **overrides)
    return get_success_data(api.create_fleet_allocation(payload, operator_headers))


# ---------------------------------------------------------------------------
# Tier 2 — capital draws
# ---------------------------------------------------------------------------

def request_draw(
    api, project_id: str, amount_cents: int, requester_headers=None, memo="Mobilisation"
) -> dict:
    """Reads the project's live version so the create is never stale."""
    headers = requester_headers or TREASURY
    version = read_project_version(api, project_id, headers)
    payload = f.disbursement_payload(project_id, amount_cents, version, memo=memo)
    return get_success_data(api.create_disbursement(payload, headers))


# ---------------------------------------------------------------------------
# Tier 3 / 4 — composite trust scenarios
# ---------------------------------------------------------------------------

def setup_two_receipt_trust(
    api,
    with_obligation=False,
    obligation_overrides=None,
    with_project=False,
    project_overrides=None,
    receive_first=True,
    receive_second=True,
):
    """A facility whose CFC trust is filled by two FINAL remittances.

    Facility: cfc rate 500 cents/day, ds_reserve_requirement_cents 5,000,000,
    om_reserve_requirement_cents 1,000,000, capital_fund_cap_cents 50,000,000.
    One ACTIVE agreement on the CUMULATIVE_YTD basis with mag_annual_cents
    12,000,000 and percentage_rent_rate_bps 1000.

    Any obligation or capital project is created (and the project approved)
    *before* any cash arrives, so the covenant flip inside the second receipt
    is what releases them.

    The 2026-01 report is accepted at 5,000,000 cents / 4,000 days and the
    2026-02 report at 20,000,000 cents / 8,000 days, producing FINAL
    remittances of 2,000,000 and 4,000,000 cents respectively.
    """
    base = setup_active_agreement(api)
    facility, agreement, operator = base["facility"], base["agreement"], base["operator"]

    obligation = None
    if with_obligation:
        obligation = create_obligation(api, facility["id"], **(obligation_overrides or {}))

    project = None
    if with_project:
        project = create_project(api, facility["id"], **(project_overrides or {}))
        project = approve_project(api, project["id"])

    report_1 = create_accepted_report(
        api,
        agreement["id"],
        operator,
        period_year=2026,
        period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    report_2 = create_accepted_report(
        api,
        agreement["id"],
        operator,
        period_year=2026,
        period_month=2,
        reported_gross_revenue_cents=20_000_000,
        reported_on_airport_transaction_days=8_000,
    )

    remittance_1 = create_remittance(api, agreement["id"], report_1["id"], operator, "FINAL")
    remittance_2 = create_remittance(api, agreement["id"], report_2["id"], operator, "FINAL")

    if receive_first:
        remittance_1 = receive_cash(api, remittance_1["id"], 2_000_000)
    if receive_second:
        remittance_2 = receive_cash(api, remittance_2["id"], 4_000_000)

    return {
        **base,
        "obligation": obligation,
        "project": project,
        "report_1": report_1,
        "report_2": report_2,
        "remittance_1": remittance_1,
        "remittance_2": remittance_2,
    }


def setup_single_receipt_trust(
    api,
    with_obligation=True,
    obligation_amount_cents=800_000,
    with_project=True,
    project_budget_cents=900_000,
    project_name="Counter millwork",
    receive=True,
):
    """A facility whose covenant flips on a single 2,000,000 cent receipt.

    Facility: cfc rate 500 cents/day, ds_reserve_requirement_cents 1,000,000,
    om_reserve_requirement_cents 0, capital_fund_cap_cents 50,000,000.  The one
    2026-01 report is accepted at 5,000,000 cents / 4,000 days, so its FINAL
    remittance expects exactly 2,000,000 cents.

    With the defaults the receipt puts 1,000,000 into the debt-service reserve
    and 1,000,000 into the capital fund, flips bond_coverage_status to
    SATISFIED, auto-funds the 800,000 cent obligation and releases the project
    from APPROVED to FUNDED.
    """
    base = setup_active_agreement(
        api,
        facility_overrides={
            "ds_reserve_requirement_cents": 1_000_000,
            "om_reserve_requirement_cents": 0,
        },
    )
    facility, agreement, operator = base["facility"], base["agreement"], base["operator"]

    obligation = None
    if with_obligation:
        obligation = create_obligation(
            api, facility["id"], amount_due_cents=obligation_amount_cents
        )

    project = None
    if with_project:
        project = create_project(
            api,
            facility["id"],
            project_name=project_name,
            budget_cents=project_budget_cents,
        )
        project = approve_project(api, project["id"])

    report = create_accepted_report(
        api,
        agreement["id"],
        operator,
        period_year=2026,
        period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    remittance = create_remittance(api, agreement["id"], report["id"], operator, "FINAL")
    if receive:
        remittance = receive_cash(api, remittance["id"], 2_000_000)

    return {
        **base,
        "obligation": obligation,
        "project": project,
        "report": report,
        "remittance": remittance,
    }


def setup_funded_project_with_requested_draw(
    api, draw_amount_cents=300_000, project_budget_cents=900_000, memo="Millwork deposit"
):
    """setup_single_receipt_trust plus one REQUESTED draw raised by fin-1."""
    scenario = setup_single_receipt_trust(
        api, project_budget_cents=project_budget_cents
    )
    scenario["disbursement"] = request_draw(
        api, scenario["project"]["id"], draw_amount_cents, TREASURY, memo=memo
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 5 — true-up settlement lifecycle
# ---------------------------------------------------------------------------

def setup_issued_settlement(
    api,
    mag_annual_cents=1_500_000,
    audited_gross_revenue_cents=5_000_000,
    issuer_headers=None,
):
    """One ACTIVE agreement with a single ACCEPTED report and an ISSUED true-up.

    The report is accepted by aud-1 while the settlement is issued by aud-2, so
    the segregation-of-duties check on issuance is satisfied.
    """
    base = setup_active_agreement(
        api, agreement_overrides={"mag_annual_cents": mag_annual_cents}
    )
    agreement, operator = base["agreement"], base["operator"]
    report = create_accepted_report(
        api,
        agreement["id"],
        operator,
        period_year=2026,
        period_month=1,
        reported_gross_revenue_cents=audited_gross_revenue_cents,
        reported_on_airport_transaction_days=4_000,
    )
    settlement = create_settlement(api, agreement["id"])
    settlement = get_success_data(
        api.issue_settlement(settlement["id"], issuer_headers or AUDITOR_2)
    )
    return {**base, "report": report, "settlement": settlement}
