"""Composite state builders.

The server is restarted before every test, so each test starts against an
empty database.  Everything a test needs must therefore be built from scratch
through the API.  The builders below assemble the recurring multi-entity chains
of the licensing domain and return the identifiers a test needs.

Every builder takes the api client as its first argument and returns a plain
dict.  Builders never assert business outcomes beyond the HTTP status of the
setup calls themselves; the tests own the assertions.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .factories import (
    brand_register_payload,
    create_audit_engagement_payload,
    create_genetic_test_payload,
    create_production_quota_payload,
    create_propagator_agreement_payload,
    create_propagator_payload,
    create_protection_filing_payload,
    create_royalty_line_item_payload,
    create_royalty_report_payload,
    create_sublicense_grant_payload,
    create_surveillance_case_payload,
    create_tag_order_payload,
    create_trial_site_payload,
    create_variety_payload,
    create_variety_trial_payload,
    evaluate_trial_payload,
    reconcile_tag_order_payload,
    sample_case_payload,
    schedule_annuity_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_propagator_headers

BREEDER = TEST_USERS["breeder_admin_headers"]
OFFICER = TEST_USERS["licensing_officer_headers"]
OFFICER_TWO = TEST_USERS["licensing_officer_two_headers"]
OFFICER_THREE = TEST_USERS["licensing_officer_three_headers"]
COORDINATOR = TEST_USERS["trial_coordinator_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


# ---------------------------------------------------------------------------
# Single-entity builders
# ---------------------------------------------------------------------------
def advance_clock(api: ApiClient, current_utc: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Move the logical clock forward and return the sweep response body."""
    response = api.set_current_utc(set_clock_payload(current_utc), headers or BREEDER)
    return get_success_data(response, 200)


def create_variety(api: ApiClient, **overrides) -> Dict[str, Any]:
    response = api.create_variety(create_variety_payload(**overrides), BREEDER)
    return get_success_data(response, 201)


def create_propagator(api: ApiClient, **overrides) -> Dict[str, Any]:
    response = api.create_propagator(create_propagator_payload(**overrides), OFFICER)
    return get_success_data(response, 201)


def create_trial_site(api: ApiClient, **overrides) -> Dict[str, Any]:
    response = api.create_trial_site(create_trial_site_payload(**overrides), COORDINATOR)
    return get_success_data(response, 201)


def create_filing(api: ApiClient, variety_id: str, **overrides) -> Dict[str, Any]:
    response = api.create_protection_filing(
        create_protection_filing_payload(variety_id, **overrides), BREEDER
    )
    return get_success_data(response, 201)


def read_version(api: ApiClient, getter, resource_id: str, headers: Dict[str, str]) -> int:
    """Re-read a parent row and return its current version for an OCC guard."""
    data = get_success_data(getter(resource_id, headers), 200)
    return data["version"]


# ---------------------------------------------------------------------------
# Protection chains
# ---------------------------------------------------------------------------
def filed_filing(api: ApiClient, variety_id: str, **overrides) -> Dict[str, Any]:
    """A protection filing moved from DRAFT to FILED."""
    filing = create_filing(api, variety_id, **overrides)
    return get_success_data(api.file_protection_filing(filing["id"], BREEDER), 200)


def granted_filing(api: ApiClient, variety_id: str, **overrides) -> Dict[str, Any]:
    """A protection filing moved all the way to GRANTED."""
    filing = filed_filing(api, variety_id, **overrides)
    return get_success_data(api.grant_protection_filing(filing["id"], BREEDER), 200)


def filing_in_maintenance(api: ApiClient, variety_id: str,
                          annuity_due_date: str = "2026-09-01T00:00:00Z",
                          annuity_grace_days: int = 30,
                          **overrides) -> Dict[str, Any]:
    """A GRANTED filing with an annuity scheduled, so it sits in MAINTENANCE_DUE."""
    filing = granted_filing(api, variety_id, **overrides)
    payload = schedule_annuity_payload(
        annuity_due_date=annuity_due_date, annuity_grace_days=annuity_grace_days
    )
    return get_success_data(api.schedule_annuity(filing["id"], payload, BREEDER), 200)


# ---------------------------------------------------------------------------
# Trial chains
# ---------------------------------------------------------------------------
#: Component scores that weight to a performance index of 85.00 at a 1.0000
#: propagation pass rate.
STRONG_TRIAL_SCORES = {
    "yield_index": 90,
    "vigor_score": 84,
    "uniformity_score": 86,
    "disease_resistance_score": 75,
    "propagation_pass_rate": 1.0000,
}
#: Component scores that weight to a performance index of 72.00 at a 1.0000
#: propagation pass rate.
MODEST_TRIAL_SCORES = {
    "yield_index": 76,
    "vigor_score": 70,
    "uniformity_score": 72,
    "disease_resistance_score": 66,
    "propagation_pass_rate": 1.0000,
}


def planted_trial(api: ApiClient, variety_id: str, trial_site_id: str,
                  plant_date: str = "2026-08-05T00:00:00Z",
                  harvest_date: str = "2026-09-20T00:00:00Z",
                  plot_count: int = 20,
                  advance_to_plant_date: bool = True) -> Dict[str, Any]:
    """A trial created and planted; the clock is moved to the plant date first."""
    trial = get_success_data(
        api.create_variety_trial(
            create_variety_trial_payload(
                variety_id, trial_site_id, plot_count=plot_count,
                plant_date=plant_date, harvest_date=harvest_date,
            ),
            COORDINATOR,
        ),
        201,
    )
    if advance_to_plant_date:
        advance_clock(api, plant_date, COORDINATOR)
    return get_success_data(api.plant_variety_trial(trial["id"], COORDINATOR), 200)


def two_region_passed_trials(api: ApiClient, variety_id: str,
                             first_site_name: str = "Wenatchee Station",
                             second_site_name: str = "Modesto Station") -> Dict[str, Any]:
    """Two certified PASSED trials in the distinct regions PNW and CAV.

    The pair drives passed_trial_region_count to 2 and the mean of the two
    performance indices, 85.00 and 72.00, to a regional_performance_index of
    78.50 -- which is what makes the variety releasable.  The clock ends at
    2026-09-20T00:00:00Z.
    """
    site_pnw = create_trial_site(api, site_name=first_site_name, region_code="PNW", plot_capacity=100)
    site_cav = create_trial_site(api, site_name=second_site_name, region_code="CAV", plot_capacity=100)
    trial_one = get_success_data(
        api.create_variety_trial(
            create_variety_trial_payload(variety_id, site_pnw["id"], plot_count=20), COORDINATOR
        ),
        201,
    )
    trial_two = get_success_data(
        api.create_variety_trial(
            create_variety_trial_payload(variety_id, site_cav["id"], plot_count=20), COORDINATOR
        ),
        201,
    )
    advance_clock(api, "2026-08-05T00:00:00Z", COORDINATOR)
    get_success_data(api.plant_variety_trial(trial_one["id"], COORDINATOR), 200)
    get_success_data(api.plant_variety_trial(trial_two["id"], COORDINATOR), 200)
    advance_clock(api, "2026-09-20T00:00:00Z", COORDINATOR)
    evaluated_one = get_success_data(
        api.evaluate_variety_trial(
            trial_one["id"], evaluate_trial_payload(**STRONG_TRIAL_SCORES), COORDINATOR
        ),
        200,
    )
    evaluated_two = get_success_data(
        api.evaluate_variety_trial(
            trial_two["id"], evaluate_trial_payload(**MODEST_TRIAL_SCORES), COORDINATOR
        ),
        200,
    )
    certified_one = get_success_data(api.certify_variety_trial(trial_one["id"], BREEDER), 200)
    certified_two = get_success_data(api.certify_variety_trial(trial_two["id"], BREEDER), 200)
    return {
        "site_pnw": site_pnw,
        "site_cav": site_cav,
        "trial_pnw": certified_one,
        "trial_cav": certified_two,
        "evaluated_pnw": evaluated_one,
        "evaluated_cav": evaluated_two,
    }


def released_variety(api: ApiClient, **overrides) -> Dict[str, Any]:
    """A variety carried to RELEASED through a GRANTED US filing and two
    PASSED trials in distinct regions.  The clock ends at 2026-09-20."""
    variety = create_variety(api, **overrides)
    filing = granted_filing(api, variety["id"])
    trials = two_region_passed_trials(api, variety["id"])
    released = get_success_data(api.release_variety(variety["id"], BREEDER), 200)
    return {"variety": released, "filing": filing, "trials": trials}


# ---------------------------------------------------------------------------
# Licensing chains
# ---------------------------------------------------------------------------
def active_agreement(api: ApiClient, quality_tier: str = "TIER_B",
                     territory_codes: Optional[List[str]] = None,
                     propagator_name: str = "Aurora Lane Nursery",
                     home_territory_code: str = "US-WA",
                     countersigner: Optional[Dict] = None,
                     **overrides) -> Dict[str, Any]:
    """A propagator plus a countersigned, therefore ACTIVE, agreement."""
    propagator = create_propagator(
        api, legal_name=propagator_name, home_territory_code=home_territory_code
    )
    agreement = get_success_data(
        api.create_propagator_agreement(
            create_propagator_agreement_payload(
                propagator["id"],
                quality_tier=quality_tier,
                territory_codes=territory_codes or ["US-WA"],
                **overrides,
            ),
            OFFICER,
        ),
        201,
    )
    active = get_success_data(
        api.countersign_agreement(agreement["id"], countersigner or OFFICER), 200
    )
    return {
        "propagator": propagator,
        "propagator_id": propagator["id"],
        "propagator_headers": make_propagator_headers(propagator["id"]),
        "agreement": active,
        "agreement_id": active["id"],
    }


def licensed_quota(api: ApiClient, quality_tier: str = "TIER_B",
                   territory_class: str = "DOMESTIC",
                   allocated_units: int = 20000,
                   season_code: str = "2026S1",
                   basis: str = "PER_PLANT",
                   variety_overrides: Optional[Dict] = None,
                   **agreement_overrides) -> Dict[str, Any]:
    """Variety -> propagator -> ACTIVE agreement -> ACTIVE production quota.

    This is the base of every royalty scenario in the domain.
    """
    variety = create_variety(api, **(variety_overrides or {}))
    chain = active_agreement(api, quality_tier=quality_tier, **agreement_overrides)
    quota = get_success_data(
        api.create_production_quota(
            create_production_quota_payload(
                chain["agreement_id"], variety["id"],
                season_code=season_code, basis=basis,
                territory_class=territory_class,
                allocated_units=allocated_units,
            ),
            OFFICER,
        ),
        201,
    )
    chain.update({"variety": variety, "variety_id": variety["id"],
                  "quota": quota, "quota_id": quota["id"]})
    return chain


def issued_tag_order(api: ApiClient, chain: Dict[str, Any],
                     requested_units: int = 12000) -> Dict[str, Any]:
    """A tag order carried from REQUESTED to ISSUED against a quota."""
    quota_version = read_version(api, api.get_production_quota, chain["quota_id"], OFFICER)
    order = get_success_data(
        api.create_tag_order(
            create_tag_order_payload(chain["quota_id"], quota_version,
                                     requested_units=requested_units),
            chain["propagator_headers"],
        ),
        201,
    )
    return get_success_data(api.issue_tag_order(order["id"], OFFICER), 200)


def reconciled_tag_order(api: ApiClient, chain: Dict[str, Any],
                         requested_units: int = 12000,
                         activated_units: Optional[int] = None) -> Dict[str, Any]:
    """A tag order carried all the way to RECONCILED, which is what puts
    activated units on the quota."""
    order = issued_tag_order(api, chain, requested_units=requested_units)
    units = requested_units if activated_units is None else activated_units
    return get_success_data(
        api.reconcile_tag_order(order["id"], reconcile_tag_order_payload(units),
                                chain["propagator_headers"]),
        200,
    )


def draft_report(api: ApiClient, chain: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """A DRAFT royalty report under the chain's agreement, created by the
    owning propagator."""
    return get_success_data(
        api.create_royalty_report(
            create_royalty_report_payload(chain["agreement_id"], **overrides),
            chain["propagator_headers"],
        ),
        201,
    )


def add_line_item(api: ApiClient, chain: Dict[str, Any], report_id: str,
                  reported_units: int, quota_id: Optional[str] = None,
                  **overrides) -> Dict[str, Any]:
    """Append a line item, reading the report's version fresh for the guard."""
    report_version = read_version(api, api.get_royalty_report, report_id,
                                  chain["propagator_headers"])
    return get_success_data(
        api.create_royalty_line_item(
            report_id,
            create_royalty_line_item_payload(
                quota_id or chain["quota_id"], reported_units, report_version, **overrides
            ),
            chain["propagator_headers"],
        ),
        201,
    )


def submitted_report(api: ApiClient, chain: Dict[str, Any], reported_units: int,
                     report_overrides: Optional[Dict] = None) -> Dict[str, Any]:
    """A report with one line item, submitted by the owning propagator."""
    report = draft_report(api, chain, **(report_overrides or {}))
    line_item = add_line_item(api, chain, report["id"], reported_units)
    submitted = get_success_data(
        api.submit_royalty_report(report["id"], chain["propagator_headers"]), 200
    )
    return {"report": submitted, "report_id": submitted["id"], "line_item": line_item,
            "line_item_id": line_item["id"]}


def accepted_report(api: ApiClient, chain: Dict[str, Any], reported_units: int,
                    report_overrides: Optional[Dict] = None,
                    accepter: Optional[Dict] = None) -> Dict[str, Any]:
    """A submitted report accepted by an officer other than the countersigner,
    which is what books the amount onto the propagator ledger."""
    bundle = submitted_report(api, chain, reported_units, report_overrides)
    accepted = get_success_data(
        api.accept_royalty_report(bundle["report_id"], accepter or OFFICER_TWO), 200
    )
    bundle["report"] = accepted
    return bundle


def royalty_chain_with_accepted_report(api: ApiClient, quality_tier: str = "TIER_A",
                                       allocated_units: int = 20000,
                                       requested_units: int = 12000,
                                       reported_units: int = 12000,
                                       variety_overrides: Optional[Dict] = None,
                                       **kwargs) -> Dict[str, Any]:
    """The full royalty spine: quota, reconciled tags, accepted report."""
    chain = licensed_quota(api, quality_tier=quality_tier,
                           allocated_units=allocated_units,
                           variety_overrides=variety_overrides, **kwargs)
    chain["tag_order"] = reconciled_tag_order(api, chain, requested_units=requested_units)
    chain.update(accepted_report(api, chain, reported_units))
    return chain


def opened_audit_engagement(api: ApiClient, chain: Dict[str, Any]) -> Dict[str, Any]:
    """An audit engagement opened against the chain's agreement and report."""
    return get_success_data(
        api.create_audit_engagement(
            create_audit_engagement_payload(chain["agreement_id"], chain["report_id"]),
            AUDITOR,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Sublicensing chains
# ---------------------------------------------------------------------------
def proposed_sublicense(api: ApiClient, chain: Dict[str, Any], variety_id: str,
                        **overrides) -> Dict[str, Any]:
    """A PROPOSED sublicense grant, reading the agreement version fresh."""
    agreement_version = read_version(api, api.get_propagator_agreement,
                                     chain["agreement_id"], OFFICER)
    return get_success_data(
        api.create_sublicense_grant(
            create_sublicense_grant_payload(
                chain["agreement_id"], variety_id, agreement_version, **overrides
            ),
            OFFICER,
        ),
        201,
    )


def active_sublicense(api: ApiClient, chain: Dict[str, Any], variety_id: str,
                      **overrides) -> Dict[str, Any]:
    grant = proposed_sublicense(api, chain, variety_id, **overrides)
    return get_success_data(api.activate_sublicense_grant(grant["id"], OFFICER), 200)


# ---------------------------------------------------------------------------
# Surveillance chains
# ---------------------------------------------------------------------------
def sampled_case(api: ApiClient, variety_id: str, sampled_unit_count: int = 40,
                 **overrides) -> Dict[str, Any]:
    """A surveillance case moved from OPEN to TESTING by sampling."""
    case = get_success_data(
        api.create_surveillance_case(
            create_surveillance_case_payload(variety_id, **overrides), AUDITOR
        ),
        201,
    )
    return get_success_data(
        api.sample_surveillance_case(case["id"], sample_case_payload(sampled_unit_count), AUDITOR),
        200,
    )


def case_with_genetic_test(api: ApiClient, variety_id: str, match_confidence: float,
                           **overrides) -> Dict[str, Any]:
    """A TESTING surveillance case carrying one genetic test."""
    case = sampled_case(api, variety_id, **overrides)
    test = get_success_data(
        api.create_genetic_test(case["id"], create_genetic_test_payload(match_confidence), AUDITOR),
        201,
    )
    return {"case": case, "case_id": case["id"], "genetic_test": test,
            "genetic_test_id": test["id"]}


# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------
def branded_variety(api: ApiClient, brand_mark_text: str = "SABLECREST",
                    **overrides) -> Dict[str, Any]:
    variety = create_variety(api, **overrides)
    registered = get_success_data(
        api.brand_register_variety(
            variety["id"], brand_register_payload(brand_mark_text=brand_mark_text), BREEDER
        ),
        200,
    )
    return registered
