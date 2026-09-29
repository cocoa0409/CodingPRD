"""Composite setup helpers.

Every helper drives the real API through PRD-declared endpoints only, and every helper
builds its preconditions from scratch: each test runs against an empty database.

The workhorse helpers return a ``scenario`` dict whose keys are the entities created so
far, so a test can read ids and versions without repeating a twenty-call preamble:

    scenario = setup_active_lease(api)
    scenario["lease"]["id"], scenario["period"]["id"], scenario["lessee_headers"]

Keys populated by the scenario builders:

``lessee``, ``lessee_headers``, ``aircraft``, ``captain``, ``first_officer``, ``lease``,
``approval``, ``certificate``, ``captain_qualification``,
``first_officer_qualification``, ``period``.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .constants import TEST_DEFAULTS
from .factories import (
    cancel_leg_payload,
    clear_conditions_payload,
    complete_checkride_payload,
    complete_leg_payload,
    consent_payload,
    create_aircraft_payload,
    create_captain_payload,
    create_crew_member_payload,
    create_crew_qualification_payload,
    create_first_officer_payload,
    create_flight_leg_payload,
    create_insurance_certificate_payload,
    create_lease_payload,
    create_lessee_payload,
    create_reliability_report_payload,
    create_settlement_invoice_payload,
    create_substitution_payload,
    determination_payload,
    dispatch_payload,
    inspect_return_payload,
    maintenance_event_payload,
    review_report_payload,
    revoke_payload,
    submit_for_approval_payload,
    terminate_lease_payload,
    void_invoice_payload,
)
from .test_users import TEST_USERS, make_billing_admin_headers, make_lessee_headers

OPS = TEST_USERS["lessor_ops_headers"]
AUTHORITY = TEST_USERS["regulatory_authority_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
SECOND_BILLING = TEST_USERS["second_billing_admin_headers"]
UNDERWRITER = TEST_USERS["insurance_underwriter_headers"]

CLOCK_AT_TERM_START = TEST_DEFAULTS["CLOCK_AT_TERM_START"]


# --------------------------------------------------------------------------- #
# Single-call helpers                                                          #
# --------------------------------------------------------------------------- #


def set_clock(api, current_utc: str, headers=None) -> None:
    """Move the server-held logical UTC clock to ``current_utc``."""
    get_success_data(api.set_current_utc(current_utc, headers or OPS))


def create_lessee(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_lessee(create_lessee_payload(**overrides), headers or BILLING)
    )


def create_aircraft(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_aircraft(create_aircraft_payload(**overrides), headers or TECH)
    )


def create_captain(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_crew_member(create_captain_payload(**overrides), headers or OPS)
    )


def create_first_officer(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_crew_member(create_first_officer_payload(**overrides), headers or OPS)
    )


def create_crew_member(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_crew_member(create_crew_member_payload(**overrides), headers or OPS)
    )


def create_lease(api, lessee_id: str, aircraft_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_lease(
            create_lease_payload(lessee_id, aircraft_id, **overrides), headers or OPS
        )
    )


def file_lease_with_authority(api, lease_id: str, headers=None, **overrides) -> dict:
    """Submit a DRAFT lease for approval; returns the opened RegulatoryApproval docket."""
    return get_success_data(
        api.submit_lease_for_approval(
            lease_id, submit_for_approval_payload(**overrides), headers or OPS
        )
    )


def record_determination(
    api, approval_id: str, determination: str = "APPROVED", headers=None, **overrides
) -> dict:
    return get_success_data(
        api.record_determination(
            approval_id,
            determination_payload(determination, **overrides),
            headers or AUTHORITY,
        )
    )


def clear_conditions(api, approval_id: str, cleared_condition_codes, headers=None) -> dict:
    return get_success_data(
        api.clear_approval_conditions(
            approval_id,
            clear_conditions_payload(cleared_condition_codes),
            headers or AUTHORITY,
        )
    )


def revoke_approval(api, approval_id: str, revocation_reason: str = "Determination withdrawn", headers=None) -> dict:
    return get_success_data(
        api.revoke_regulatory_approval(
            approval_id, revoke_payload(revocation_reason), headers or AUTHORITY
        )
    )


def issue_insurance_certificate(api, lease_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_insurance_certificate(
            create_insurance_certificate_payload(lease_id, **overrides),
            headers or UNDERWRITER,
        )
    )


def revoke_insurance_certificate(
    api, certificate_id: str, revocation_reason: str = "Cover withdrawn by underwriter", headers=None
) -> dict:
    return get_success_data(
        api.revoke_insurance_certificate(
            certificate_id, revoke_payload(revocation_reason), headers or UNDERWRITER
        )
    )


def qualify_crew_member(api, crew_member_id: str, lease_id: str, headers=None, **checkride) -> dict:
    """Enrol a crew member on a lease and complete the checkride, landing QUALIFIED."""
    qualification = get_success_data(
        api.create_crew_qualification(
            create_crew_qualification_payload(crew_member_id, lease_id),
            headers or OPS,
        )
    )
    return get_success_data(
        api.complete_checkride(
            qualification["id"], complete_checkride_payload(**checkride), headers or OPS
        )
    )


def activate_lease(api, lease_id: str, headers=None) -> dict:
    return get_success_data(api.activate_lease(lease_id, headers or OPS))


def record_maintenance_event(api, aircraft_id: str, event_type: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.record_maintenance_event(
            aircraft_id, maintenance_event_payload(event_type, **overrides), headers or TECH
        )
    )


# --------------------------------------------------------------------------- #
# Tier 1 / Tier 2: lease state progression                                     #
# --------------------------------------------------------------------------- #


def setup_draft_lease(
    api,
    clock: Optional[str] = CLOCK_AT_TERM_START,
    lessee_overrides: Optional[dict] = None,
    aircraft_overrides: Optional[dict] = None,
    lease_overrides: Optional[dict] = None,
    with_first_officer: bool = True,
) -> dict:
    """Lessee + airframe + captain (+ first officer) + a DRAFT lease over them."""
    if clock:
        set_clock(api, clock)
    lessee = create_lessee(api, **(lessee_overrides or {}))
    aircraft = create_aircraft(api, **(aircraft_overrides or {}))
    captain = create_captain(api)
    first_officer = create_first_officer(api) if with_first_officer else None
    lease = create_lease(api, lessee["id"], aircraft["id"], **(lease_overrides or {}))
    return {
        "lessee": lessee,
        "lessee_headers": make_lessee_headers(lessee["id"]),
        "aircraft": aircraft,
        "captain": captain,
        "first_officer": first_officer,
        "lease": lease,
    }


def setup_filed_lease(api, determination: Optional[str] = None, **kwargs) -> dict:
    """DRAFT lease submitted to the authority (lease PENDING_REGULATORY_APPROVAL).

    Pass ``determination`` to have the authority rule on the docket immediately;
    extra determination fields go in ``determination_overrides``.
    """
    determination_overrides = kwargs.pop("determination_overrides", None) or {}
    docket_overrides = kwargs.pop("docket_overrides", None) or {}
    scenario = setup_draft_lease(api, **kwargs)
    scenario["approval"] = file_lease_with_authority(
        api, scenario["lease"]["id"], **docket_overrides
    )
    if determination:
        scenario["approval"] = record_determination(
            api, scenario["approval"]["id"], determination, **determination_overrides
        )
    scenario["lease"] = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    return scenario


def setup_approved_lease(api, with_certificate: bool = True, **kwargs) -> dict:
    """Lease APPROVED on a live determination, with conforming cover in place."""
    certificate_overrides = kwargs.pop("certificate_overrides", None) or {}
    scenario = setup_filed_lease(api, determination="APPROVED", **kwargs)
    if with_certificate:
        scenario["certificate"] = issue_insurance_certificate(
            api, scenario["lease"]["id"], **certificate_overrides
        )
    return scenario


def setup_active_lease(api, qualify_crew: bool = True, **kwargs) -> dict:
    """Full activation chain: APPROVED lease + qualified crew, then activate.

    Leaves the lease ACTIVE with its airframe ASSIGNED, the deposit seeded and the
    first UtilizationPeriod OPEN (available as ``scenario["period"]``).
    """
    checkride_overrides = kwargs.pop("checkride_overrides", None) or {}
    scenario = setup_approved_lease(api, **kwargs)
    lease_id = scenario["lease"]["id"]
    if qualify_crew:
        scenario["captain_qualification"] = qualify_crew_member(
            api, scenario["captain"]["id"], lease_id, **checkride_overrides
        )
        if scenario.get("first_officer"):
            scenario["first_officer_qualification"] = qualify_crew_member(
                api, scenario["first_officer"]["id"], lease_id, **checkride_overrides
            )
    scenario["lease"] = activate_lease(api, lease_id)
    scenario["period"] = first_open_period(api, lease_id)
    return scenario


def refresh_scenario(api, scenario: dict) -> dict:
    """Re-read the lease, airframe, crew and open period after a cascade."""
    scenario["lease"] = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    scenario["aircraft"] = get_success_data(
        api.get_aircraft(scenario["aircraft"]["id"], TECH)
    )
    scenario["captain"] = get_success_data(
        api.get_crew_member(scenario["captain"]["id"], OPS)
    )
    if scenario.get("first_officer"):
        scenario["first_officer"] = get_success_data(
            api.get_crew_member(scenario["first_officer"]["id"], OPS)
        )
    if scenario.get("period"):
        scenario["period"] = get_success_data(
            api.get_utilization_period(scenario["period"]["id"], BILLING)
        )
    return scenario


# --------------------------------------------------------------------------- #
# Tier 3: flight legs                                                          #
# --------------------------------------------------------------------------- #


def schedule_leg(
    api,
    scenario: dict,
    scheduled_out: str = "2026-09-05T08:00:00Z",
    scheduled_in: str = "2026-09-05T10:00:00Z",
    headers=None,
    **overrides,
) -> dict:
    """Create one SCHEDULED leg on the scenario's lease, airframe and crew pair."""
    payload = create_flight_leg_payload(
        scenario["lease"]["id"],
        overrides.pop("aircraft_id", scenario["aircraft"]["id"]),
        overrides.pop("captain_id", scenario["captain"]["id"]),
        overrides.pop(
            "first_officer_id",
            (scenario.get("first_officer") or scenario["captain"])["id"],
        ),
        scheduled_out=scheduled_out,
        scheduled_in=scheduled_in,
        **overrides,
    )
    return get_success_data(api.create_flight_leg(payload, headers or OPS))


def dispatch_leg(api, leg_id: str, actual_out: str, headers=None) -> dict:
    return get_success_data(
        api.dispatch_flight_leg(leg_id, dispatch_payload(actual_out), headers or OPS)
    )


def complete_leg(
    api, leg_id: str, actual_in: str, technical_delay_minutes: Optional[int] = None, headers=None
) -> dict:
    extra = (
        {"technical_delay_minutes": technical_delay_minutes}
        if technical_delay_minutes is not None
        else {}
    )
    return get_success_data(
        api.complete_flight_leg(
            leg_id, complete_leg_payload(actual_in, **extra), headers or OPS
        )
    )


def fly_leg(
    api,
    scenario: dict,
    scheduled_out: str = "2026-09-05T08:00:00Z",
    scheduled_in: str = "2026-09-05T10:00:00Z",
    actual_out: Optional[str] = None,
    actual_in: Optional[str] = None,
    technical_delay_minutes: Optional[int] = None,
    **overrides,
) -> dict:
    """Create, dispatch and complete one leg. Returns the COMPLETED leg.

    ``actual_out`` / ``actual_in`` default to the scheduled instants, so the block time
    equals the scheduled block time unless a test pins different actuals.
    """
    leg = schedule_leg(api, scenario, scheduled_out, scheduled_in, **overrides)
    dispatch_leg(api, leg["id"], actual_out or scheduled_out)
    return complete_leg(
        api, leg["id"], actual_in or scheduled_in, technical_delay_minutes
    )


def cancel_leg(
    api,
    leg_id: str,
    cancelling_party: str = "LESSEE",
    cancel_reason: str = "COMMERCIAL",
    headers=None,
) -> dict:
    return get_success_data(
        api.cancel_flight_leg(
            leg_id, cancel_leg_payload(cancelling_party, cancel_reason), headers or OPS
        )
    )


# --------------------------------------------------------------------------- #
# Tier 4: months, reliability and settlement                                   #
# --------------------------------------------------------------------------- #


def list_periods(api, lease_id: str, headers=None, **filters) -> List[dict]:
    params = {"lease_id": lease_id}
    params.update(filters)
    return get_success_data(
        api.list_utilization_periods(headers or BILLING, params=params)
    )


def first_open_period(api, lease_id: str, headers=None) -> dict:
    """The lease's earliest utilization period — the one activation opened."""
    periods = list_periods(api, lease_id, headers=headers)
    assert periods, f"Setup failed: no utilization period exists for lease {lease_id}"
    return periods[0]


def period_for_month(api, lease_id: str, period_month: str, headers=None) -> dict:
    periods = list_periods(api, lease_id, headers=headers, period_month=period_month)
    assert periods, f"Setup failed: no {period_month} period exists for lease {lease_id}"
    return periods[0]


def close_month(api, period_id: str, headers=None) -> dict:
    """Close a month, recomputing every charge field under the FINAL variant."""
    return get_success_data(api.close_utilization_period(period_id, headers or BILLING))


def file_reliability_report(
    api, scenario: dict, period_month: str = "2026-09", decision: Optional[str] = "ACCEPT", **overrides
) -> dict:
    """File the monthly technical report and, by default, have the lessee ACCEPT it."""
    report = get_success_data(
        api.create_reliability_report(
            create_reliability_report_payload(
                scenario["lease"]["id"],
                overrides.pop("aircraft_id", scenario["aircraft"]["id"]),
                period_month,
            ),
            TECH,
        )
    )
    if decision:
        report = get_success_data(
            api.review_reliability_report(
                report["id"],
                review_report_payload(decision, **overrides),
                scenario["lessee_headers"],
            )
        )
    return report


def prepare_invoice(
    api,
    period: dict,
    due_on: str = "2026-10-31",
    variant: Optional[str] = None,
    headers=None,
    expected_period_version: Optional[int] = None,
) -> dict:
    """Prepare a settlement invoice against a PENDING_SETTLEMENT period."""
    extra = {"variant": variant} if variant else {}
    payload = create_settlement_invoice_payload(
        period["id"],
        period["version"] if expected_period_version is None else expected_period_version,
        due_on,
        **extra,
    )
    return get_success_data(api.create_settlement_invoice(payload, headers or BILLING))


def approve_invoice(api, invoice_id: str, headers=None) -> dict:
    """Approve an invoice with a second pair of eyes (a different BillingAdmin id)."""
    return get_success_data(
        api.approve_settlement_invoice(invoice_id, headers or SECOND_BILLING)
    )


def issue_invoice(api, invoice_id: str, headers=None) -> dict:
    return get_success_data(
        api.issue_settlement_invoice(invoice_id, headers or SECOND_BILLING)
    )


def void_invoice(api, invoice_id: str, void_reason: str = "Corrected settlement", headers=None) -> dict:
    return get_success_data(
        api.void_settlement_invoice(invoice_id, void_invoice_payload(void_reason), headers or BILLING)
    )


def prepare_approve_and_issue_invoice(
    api,
    scenario: dict,
    period: Optional[dict] = None,
    due_on: str = "2026-10-31",
    variant: Optional[str] = None,
    period_month: str = "2026-09",
    with_accepted_report: bool = True,
) -> dict:
    """Walk one month's invoice from preparation to ISSUED.

    Approval requires an ACCEPTED reliability report for the lease and month, so one is
    filed and accepted unless the caller already arranged it. The preparer and the
    approver use different operator identifiers, as the second-pair-of-eyes rule demands.
    """
    period = period or get_success_data(
        api.get_utilization_period(scenario["period"]["id"], BILLING)
    )
    if with_accepted_report:
        file_reliability_report(api, scenario, period_month=period_month)
        period = get_success_data(api.get_utilization_period(period["id"], BILLING))
    invoice = prepare_invoice(api, period, due_on=due_on, variant=variant)
    invoice = approve_invoice(api, invoice["id"])
    return issue_invoice(api, invoice["id"])


def setup_settled_month(
    api,
    leg_plan: Optional[List[dict]] = None,
    period_month: str = "2026-09",
    **kwargs,
) -> dict:
    """Active lease, flown month, month closed and a FINAL invoice ISSUED.

    ``leg_plan`` is a list of kwargs dicts handed to ``fly_leg``; the default flies one
    two-hour revenue leg. Leaves the period SETTLED and adds ``scenario["invoice"]``.
    """
    scenario = setup_active_lease(api, **kwargs)
    for leg_kwargs in leg_plan if leg_plan is not None else [{}]:
        fly_leg(api, scenario, **leg_kwargs)
    scenario["period"] = close_month(api, scenario["period"]["id"])
    scenario["invoice"] = prepare_approve_and_issue_invoice(
        api, scenario, period=scenario["period"], period_month=period_month
    )
    scenario["period"] = get_success_data(
        api.get_utilization_period(scenario["period"]["id"], BILLING)
    )
    return scenario


# --------------------------------------------------------------------------- #
# Substitutions                                                                #
# --------------------------------------------------------------------------- #


def add_substitute_candidate(api, **overrides) -> dict:
    """Register a second airframe eligible to stand in for the primary."""
    defaults = {
        "tail_number": "G-SUB1",
        "hours_since_last_check": 80.00,
        "cycles_since_last_check": 20,
    }
    defaults.update(overrides)
    return create_aircraft(api, **defaults)


def request_substitution(api, scenario: dict, headers=None, **overrides) -> dict:
    """Request a substitution against the scenario's lease at its current version."""
    lease = scenario["lease"]
    payload = create_substitution_payload(
        lease["id"],
        overrides.pop("original_aircraft_id", scenario["aircraft"]["id"]),
        overrides.pop("expected_lease_version", lease["version"]),
        **overrides,
    )
    return get_success_data(api.create_substitution(payload, headers or OPS))


def consent_to_substitution(
    api, scenario: dict, substitution_id: str, decision: str = "GRANT", **overrides
) -> dict:
    return get_success_data(
        api.consent_substitution(
            substitution_id,
            consent_payload(decision, **overrides),
            scenario["lessee_headers"],
        )
    )


def effectuate_substitution(api, substitution_id: str, headers=None) -> dict:
    return get_success_data(
        api.effectuate_substitution(substitution_id, headers or OPS)
    )


# --------------------------------------------------------------------------- #
# Tier 5: termination, redelivery and closure                                  #
# --------------------------------------------------------------------------- #


def terminate_lease(api, lease_id: str, termination_reason: str = "EXPIRY", headers=None) -> dict:
    """Serve termination; returns the ReturnCondition created by the transition."""
    return get_success_data(
        api.terminate_lease(
            lease_id, terminate_lease_payload(termination_reason), headers or OPS
        )
    )


def setup_terminating_lease(api, leg_plan: Optional[List[dict]] = None, **kwargs) -> dict:
    """Active lease driven to TERMINATING, with its PENDING_INSPECTION return record.

    Adds ``scenario["return_condition"]``.
    """
    scenario = setup_active_lease(api, **kwargs)
    for leg_kwargs in leg_plan or []:
        fly_leg(api, scenario, **leg_kwargs)
    scenario["return_condition"] = terminate_lease(api, scenario["lease"]["id"])
    scenario["lease"] = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    return scenario


def inspect_return(
    api,
    return_id: str,
    hours_since_check_at_return: float,
    cycles_since_check_at_return: int,
    fuel_on_board_kg: int,
    discrepancy_codes=None,
    headers=None,
) -> dict:
    return get_success_data(
        api.inspect_return_condition(
            return_id,
            inspect_return_payload(
                hours_since_check_at_return,
                cycles_since_check_at_return,
                fuel_on_board_kg,
                discrepancy_codes,
            ),
            headers or TECH,
        )
    )


def fly_repositioning_leg(
    api,
    scenario: dict,
    scheduled_out: str = "2026-12-20T08:00:00Z",
    scheduled_in: str = "2026-12-20T09:30:00Z",
    **overrides,
) -> dict:
    """Fly the ferry to the redelivery station, ready for return-record closure."""
    overrides.setdefault("leg_class", "REPOSITIONING")
    overrides.setdefault("dest_icao", scenario["lease"]["redelivery_icao"])
    return fly_leg(api, scenario, scheduled_out, scheduled_in, **overrides)
