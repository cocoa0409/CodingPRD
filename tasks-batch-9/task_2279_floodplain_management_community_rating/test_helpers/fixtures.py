"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient success validator so that a broken
precondition surfaces as a setup failure rather than a confusing assertion.

Naming follows the domain: communities, FIRM panels, parcels, structures,
permits, elevation certificates, the improvement ledger, determination cases,
post-disaster inspections, enforcement, repetitive loss areas, credit
submissions and recertification cycles.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    amend_certificate_payload,
    assess_inspection_payload,
    create_community_payload,
    create_crs_cycle_payload,
    create_loss_area_payload,
    create_permit_payload,
    create_property_payload,
    create_remediation_order_payload,
    create_structure_payload,
    create_violation_payload,
    file_certificate_payload,
    file_firm_panel_payload,
    higher_standard_payload,
    improvement_record_payload,
    inspection_sweep_payload,
    launch_outreach_payload,
    review_certificate_payload,
    review_permit_payload,
    reversal_record_payload,
    verify_higher_standard_payload,
)
from .test_users import TEST_USERS, make_property_owner_headers

COORDINATOR = TEST_USERS["coordinator_headers"]
ADMINISTRATOR = TEST_USERS["administrator_headers"]
APPEALS_BOARD = TEST_USERS["appeals_board_headers"]


# ==========================================================================
# Clock
# ==========================================================================

def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical UTC clock forward to `to_iso8601`."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or COORDINATOR))


# ==========================================================================
# Tier 1 — single-entity builders
# ==========================================================================

def register_community(**overrides) -> dict:
    return get_success_data(
        api_client.create_community(create_community_payload(**overrides), COORDINATOR)
    )


def read_community(community_id: str) -> dict:
    return get_success_data(api_client.get_community(community_id, COORDINATOR))


def amend_standards(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.amend_community_standards(community_id, dict(overrides), ADMINISTRATOR)
    )


def file_panel(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.file_firm_panel(file_firm_panel_payload(community_id, **overrides), COORDINATOR)
    )


def activate_panel(panel_id: str) -> dict:
    return get_success_data(api_client.activate_firm_panel(panel_id, COORDINATOR))


def create_effective_panel(community_id: str, **overrides) -> dict:
    """File a panel and activate it, so that it is the governing map."""
    panel = file_panel(community_id, **overrides)
    return activate_panel(panel["id"])


def add_property(community_id: str, firm_panel_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_property(
            create_property_payload(community_id, firm_panel_id, **overrides), ADMINISTRATOR
        )
    )


def read_property(property_id: str) -> dict:
    return get_success_data(api_client.get_property(property_id, ADMINISTRATOR))


def add_structure(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_structure(create_structure_payload(property_id, **overrides), ADMINISTRATOR)
    )


def read_structure(structure_id: str) -> dict:
    return get_success_data(api_client.get_structure(structure_id, ADMINISTRATOR))


def correct_market_value(structure_id: str, market_value_usd: float) -> dict:
    return get_success_data(
        api_client.correct_structure_market_value(
            structure_id, {"market_value_usd": market_value_usd}, ADMINISTRATOR
        )
    )


# ==========================================================================
# Tier 2 — parcel / structure scenarios
# ==========================================================================

def setup_community_with_panel(community_overrides=None, panel_overrides=None) -> dict:
    """A registered community whose FIRM panel is EFFECTIVE."""
    community = register_community(**(community_overrides or {}))
    panel = create_effective_panel(community["id"], **(panel_overrides or {}))
    return {"community": community, "panel": panel}


def setup_parcel(community_overrides=None, panel_overrides=None,
                 property_overrides=None) -> dict:
    """Community + EFFECTIVE panel + one parcel, with the parcel owner's headers."""
    base = setup_community_with_panel(community_overrides, panel_overrides)
    prop = add_property(
        base["community"]["id"], base["panel"]["id"], **(property_overrides or {})
    )
    base["property"] = prop
    base["owner_headers"] = make_property_owner_headers(prop["id"])
    return base


def setup_structure(community_overrides=None, panel_overrides=None,
                    property_overrides=None, structure_overrides=None) -> dict:
    """Community + EFFECTIVE panel + parcel + one structure."""
    scenario = setup_parcel(community_overrides, panel_overrides, property_overrides)
    scenario["structure"] = add_structure(
        scenario["property"]["id"], **(structure_overrides or {})
    )
    return scenario


# ==========================================================================
# Tier 3 — the improvement ledger
# ==========================================================================

def append_record(structure_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.append_improvement_record(
            improvement_record_payload(structure_id, **overrides), ADMINISTRATOR
        )
    )


def append_reversal(structure_id: str, reverses_record_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.append_improvement_record(
            reversal_record_payload(structure_id, reverses_record_id, **overrides), ADMINISTRATOR
        )
    )


def setup_ledger(records, community_overrides=None, panel_overrides=None,
                 property_overrides=None, structure_overrides=None) -> dict:
    """Build a structure and append `records` (a list of payload override dicts)
    to its ledger in order.  Returns the scenario plus the created records."""
    scenario = setup_structure(
        community_overrides, panel_overrides, property_overrides, structure_overrides
    )
    scenario["records"] = [
        append_record(scenario["structure"]["id"], **overrides) for overrides in records
    ]
    scenario["structure"] = read_structure(scenario["structure"]["id"])
    return scenario


# ==========================================================================
# Tier 3 — determination cases and appeals
# ==========================================================================

def open_case(structure_id: str, method: str = "CUMULATIVE",
              expected_structure_version=None, headers=None) -> dict:
    """Open a determination case, reading the structure's live version when the
    optimistic-concurrency token is not pinned by the caller."""
    if expected_structure_version is None:
        expected_structure_version = read_structure(structure_id)["version"]
    payload = {
        "structure_id": structure_id,
        "method": method,
        "expected_structure_version": expected_structure_version,
    }
    return get_success_data(
        api_client.open_determination_case(payload, headers or ADMINISTRATOR)
    )


def determine_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.determine_case(case_id, headers or ADMINISTRATOR))


def appeal_case(case_id: str, owner_headers, appeal_basis="Survey disputes the cost basis") -> dict:
    return get_success_data(
        api_client.appeal_case(case_id, {"appeal_basis": appeal_basis}, owner_headers)
    )


def decide_appeal(case_id: str, decision: str, headers=None, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.decide_appeal(case_id, payload, headers or APPEALS_BOARD)
    )


def setup_determined_case(records=None, method="CUMULATIVE", determiner_headers=None,
                          **scenario_overrides) -> dict:
    """A structure with a ledger, a determination case, and the determination
    already recorded.  Returns the scenario plus `case`."""
    records = records if records is not None else [
        {"record_type": "IMPROVEMENT", "event_date": "2026-03-01T00:00:00Z",
         "cost_usd": 120_000.00}
    ]
    scenario = setup_ledger(records, **scenario_overrides)
    case = open_case(scenario["structure"]["id"], method=method)
    scenario["case"] = determine_case(case["id"], headers=determiner_headers)
    scenario["structure"] = read_structure(scenario["structure"]["id"])
    return scenario


def setup_appealed_case(records=None, method="CUMULATIVE", determiner_headers=None,
                        **scenario_overrides) -> dict:
    """A DETERMINED case that the parcel owner has appealed."""
    scenario = setup_determined_case(
        records=records, method=method, determiner_headers=determiner_headers,
        **scenario_overrides
    )
    scenario["case"] = appeal_case(scenario["case"]["id"], scenario["owner_headers"])
    return scenario


# ==========================================================================
# Tier 3 — the permit lifecycle
# ==========================================================================

def start_permit(property_id: str, structure_id: str, owner_headers, **overrides) -> dict:
    return get_success_data(
        api_client.create_permit(
            create_permit_payload(property_id, structure_id, **overrides), owner_headers
        )
    )


def submit_permit(permit_id: str, owner_headers, **payload) -> dict:
    return get_success_data(
        api_client.submit_permit(permit_id, owner_headers, dict(payload) or None)
    )


def review_permit(permit_id: str, decision: str, headers=None, **extra) -> dict:
    return get_success_data(
        api_client.review_permit(
            permit_id, review_permit_payload(decision, **extra), headers or ADMINISTRATOR
        )
    )


def issue_permit(permit_id: str, headers=None) -> dict:
    return get_success_data(api_client.issue_permit(permit_id, headers or ADMINISTRATOR))


def close_permit(permit_id: str, headers=None) -> dict:
    return get_success_data(api_client.close_permit(permit_id, headers or ADMINISTRATOR))


def read_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, ADMINISTRATOR))


def setup_permit_under_review(permit_overrides=None, submit_overrides=None,
                              **scenario_overrides) -> dict:
    """Structure scenario + a permit submitted for floodplain review."""
    scenario = setup_structure(**scenario_overrides)
    permit = start_permit(
        scenario["property"]["id"], scenario["structure"]["id"], scenario["owner_headers"],
        **(permit_overrides or {})
    )
    scenario["permit"] = submit_permit(
        permit["id"], scenario["owner_headers"], **(submit_overrides or {})
    )
    return scenario


def setup_approved_permit(permit_overrides=None, submit_overrides=None,
                          **scenario_overrides) -> dict:
    scenario = setup_permit_under_review(permit_overrides, submit_overrides, **scenario_overrides)
    scenario["permit"] = review_permit(scenario["permit"]["id"], "APPROVE")
    return scenario


def setup_issued_permit(permit_overrides=None, submit_overrides=None,
                        **scenario_overrides) -> dict:
    scenario = setup_approved_permit(permit_overrides, submit_overrides, **scenario_overrides)
    scenario["permit"] = issue_permit(scenario["permit"]["id"])
    return scenario


# ==========================================================================
# Tier 3 — elevation certificates
# ==========================================================================

def file_certificate(permit_id: str, structure_id: str, owner_headers, **overrides) -> dict:
    return get_success_data(
        api_client.file_certificate(
            file_certificate_payload(permit_id, structure_id, **overrides), owner_headers
        )
    )


def review_certificate(certificate_id: str, decision: str, headers=None, **extra) -> dict:
    return get_success_data(
        api_client.review_certificate(
            certificate_id, review_certificate_payload(decision, **extra), headers or ADMINISTRATOR
        )
    )


def amend_certificate(certificate_id: str, owner_headers, **overrides) -> dict:
    return get_success_data(
        api_client.amend_certificate(
            certificate_id, amend_certificate_payload(**overrides), owner_headers
        )
    )


def read_certificate(certificate_id: str) -> dict:
    return get_success_data(api_client.get_certificate(certificate_id, ADMINISTRATOR))


def setup_filed_certificate(certificate_overrides=None, permit_overrides=None,
                            submit_overrides=None, **scenario_overrides) -> dict:
    """An ISSUED permit with an elevation certificate filed against it."""
    scenario = setup_issued_permit(permit_overrides, submit_overrides, **scenario_overrides)
    scenario["certificate"] = file_certificate(
        scenario["permit"]["id"], scenario["structure"]["id"], scenario["owner_headers"],
        **(certificate_overrides or {})
    )
    return scenario


def setup_accepted_certificate(certificate_overrides=None, permit_overrides=None,
                               submit_overrides=None, **scenario_overrides) -> dict:
    """A FINISHED_CONSTRUCTION certificate accepted on review."""
    scenario = setup_filed_certificate(
        certificate_overrides, permit_overrides, submit_overrides, **scenario_overrides
    )
    scenario["certificate"] = review_certificate(scenario["certificate"]["id"], "ACCEPT")
    scenario["structure"] = read_structure(scenario["structure"]["id"])
    return scenario


def setup_deficient_certificate(certificate_overrides=None, deficiency_codes=None,
                                permit_overrides=None, submit_overrides=None,
                                **scenario_overrides) -> dict:
    scenario = setup_filed_certificate(
        certificate_overrides, permit_overrides, submit_overrides, **scenario_overrides
    )
    scenario["certificate"] = review_certificate(
        scenario["certificate"]["id"], "DEFICIENT",
        deficiency_codes=deficiency_codes or ["MISSING_PHOTOS"],
    )
    return scenario


# ==========================================================================
# Tier 3 — post-disaster inspections
# ==========================================================================

def run_sweep(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.open_inspection_sweep(
            community_id, inspection_sweep_payload(**overrides), ADMINISTRATOR
        )
    )


def assess_inspection(inspection_id: str, damage_cost_usd: float, **overrides) -> dict:
    return get_success_data(
        api_client.assess_inspection(
            inspection_id, assess_inspection_payload(damage_cost_usd, **overrides), ADMINISTRATOR
        )
    )


def finalize_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.finalize_inspection(inspection_id, ADMINISTRATOR))


def read_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, ADMINISTRATOR))


def setup_scheduled_inspection(sweep_overrides=None, **scenario_overrides) -> dict:
    """Structure scenario + one SCHEDULED inspection produced by a sweep."""
    scenario = setup_structure(**scenario_overrides)
    sweep = run_sweep(scenario["community"]["id"], **(sweep_overrides or {}))
    scenario["sweep"] = sweep
    scenario["inspection"] = read_inspection(sweep["inspection_ids"][0])
    return scenario


def setup_assessed_inspection(damage_cost_usd=120_000.00, claim_paid_amount_usd=None,
                              sweep_overrides=None, **scenario_overrides) -> dict:
    scenario = setup_scheduled_inspection(sweep_overrides, **scenario_overrides)
    extra = {} if claim_paid_amount_usd is None else {
        "claim_paid_amount_usd": claim_paid_amount_usd
    }
    scenario["inspection"] = assess_inspection(
        scenario["inspection"]["id"], damage_cost_usd, **extra
    )
    return scenario


# ==========================================================================
# Tier 3 — enforcement
# ==========================================================================

def issue_violation(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_violation(
            create_violation_payload(property_id, **overrides), ADMINISTRATOR
        )
    )


def resolve_violation(violation_id: str, resolution: str, **extra) -> dict:
    payload = {"resolution": resolution}
    payload.update(extra)
    return get_success_data(
        api_client.resolve_violation(violation_id, payload, ADMINISTRATOR)
    )


def issue_order(violation_id: str, deadline_at: str = "2026-09-01T00:00:00Z", **overrides) -> dict:
    return get_success_data(
        api_client.create_remediation_order(
            create_remediation_order_payload(violation_id, deadline_at, **overrides), ADMINISTRATOR
        )
    )


def extend_order(order_id: str, deadline_at: str) -> dict:
    return get_success_data(
        api_client.extend_remediation_order(order_id, {"deadline_at": deadline_at}, ADMINISTRATOR)
    )


def resolve_order(order_id: str, resolution: str) -> dict:
    return get_success_data(
        api_client.resolve_remediation_order(order_id, {"resolution": resolution}, ADMINISTRATOR)
    )


def read_compliance_summary(community_id: str) -> dict:
    return get_success_data(api_client.get_compliance_summary(community_id, ADMINISTRATOR))


def setup_violation_with_order(violation_overrides=None,
                               order_deadline_at="2026-09-01T00:00:00Z",
                               **scenario_overrides) -> dict:
    """Parcel scenario + one violation + one ISSUED remediation order."""
    scenario = setup_parcel(**scenario_overrides)
    scenario["violation"] = issue_violation(
        scenario["property"]["id"], **(violation_overrides or {})
    )
    scenario["order"] = issue_order(scenario["violation"]["id"], order_deadline_at)
    return scenario


def raise_community_to_probation(property_id: str) -> list:
    """Open two MAJOR violations — 6 points each — so the raw score is 12 and the
    tier is ON_PROBATION.  Returns the violations created."""
    return [
        issue_violation(property_id, violation_type="NO_PERMIT", severity="MAJOR"),
        issue_violation(property_id, violation_type="UNPERMITTED_FILL", severity="MAJOR"),
    ]


def raise_community_to_suspension(property_id: str) -> list:
    """Open three CRITICAL violations — 12 points each — so the raw score is 36
    and the tier is SUSPENDED.  Returns the violations created."""
    return [
        issue_violation(property_id, violation_type="NO_PERMIT", severity="CRITICAL"),
        issue_violation(property_id, violation_type="UNPERMITTED_FILL", severity="CRITICAL"),
        issue_violation(property_id, violation_type="MISSING_CERTIFICATE", severity="CRITICAL"),
    ]


# ==========================================================================
# Tier 4 — repetitive loss areas and outreach
# ==========================================================================

def delineate_area(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_loss_area(create_loss_area_payload(community_id, **overrides), ADMINISTRATOR)
    )


def analyze_area(area_id: str) -> dict:
    return get_success_data(api_client.analyze_loss_area(area_id, ADMINISTRATOR))


def designate_area(area_id: str) -> dict:
    return get_success_data(api_client.designate_loss_area(area_id, ADMINISTRATOR))


def read_area(area_id: str) -> dict:
    return get_success_data(api_client.get_loss_area(area_id, ADMINISTRATOR))


def launch_outreach(area_id: str, crs_cycle_id: str, target_property_count: int) -> dict:
    return get_success_data(
        api_client.launch_outreach(
            area_id, launch_outreach_payload(crs_cycle_id, target_property_count), ADMINISTRATOR
        )
    )


def record_delivery(area_id: str, delivered_increment: int) -> dict:
    return get_success_data(
        api_client.record_outreach_delivery(
            area_id, {"delivered_increment": delivered_increment}, ADMINISTRATOR
        )
    )


def complete_outreach(area_id: str) -> dict:
    return get_success_data(api_client.complete_outreach(area_id, ADMINISTRATOR))


def setup_designated_area(area_overrides=None, **scenario_overrides) -> dict:
    """Parcel scenario + an analyzed and DESIGNATED repetitive loss area whose
    area_code matches the parcel's mapped_area_code."""
    scenario = setup_parcel(**scenario_overrides)
    area = delineate_area(scenario["community"]["id"], **(area_overrides or {}))
    analyze_area(area["id"])
    scenario["area"] = designate_area(area["id"])
    return scenario


def setup_outreach_in_progress(target_property_count=None, cycle_overrides=None,
                               area_overrides=None, **scenario_overrides) -> dict:
    """A DESIGNATED area with an in-flight outreach effort against an OPEN cycle."""
    scenario = setup_designated_area(area_overrides, **scenario_overrides)
    scenario["cycle"] = open_cycle(scenario["community"]["id"], **(cycle_overrides or {}))
    target = (
        target_property_count
        if target_property_count is not None
        else max(scenario["area"]["property_count"], 1)
    )
    scenario["area"] = launch_outreach(
        scenario["area"]["id"], scenario["cycle"]["id"], target
    )
    return scenario


# ==========================================================================
# Tier 4 — credit submissions
# ==========================================================================

def draft_standard(community_id: str, expected_community_version=None, **overrides) -> dict:
    """Draft a credit submission, reading the community's live version when the
    optimistic-concurrency token is not pinned by the caller."""
    if expected_community_version is None:
        expected_community_version = read_community(community_id)["version"]
    return get_success_data(
        api_client.draft_higher_standard(
            higher_standard_payload(community_id, expected_community_version, **overrides),
            ADMINISTRATOR,
        )
    )


def submit_standard(standard_id: str) -> dict:
    return get_success_data(api_client.submit_higher_standard(standard_id, ADMINISTRATOR))


def verify_standard(standard_id: str, decision: str = "VERIFY", **extra) -> dict:
    return get_success_data(
        api_client.verify_higher_standard(
            standard_id, verify_higher_standard_payload(decision, **extra), COORDINATOR
        )
    )


def read_standard(standard_id: str) -> dict:
    return get_success_data(api_client.get_higher_standard(standard_id, COORDINATOR))


def setup_submitted_standard(community_id: str, **overrides) -> dict:
    standard = draft_standard(community_id, **overrides)
    return submit_standard(standard["id"])


def setup_verified_standard(community_id: str, **overrides) -> dict:
    """Draft, submit and verify one credit submission for `community_id`."""
    standard = setup_submitted_standard(community_id, **overrides)
    return verify_standard(standard["id"])


# ==========================================================================
# Tier 5 — recertification cycles
# ==========================================================================

def open_cycle(community_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_crs_cycle(create_crs_cycle_payload(community_id, **overrides), COORDINATOR)
    )


def submit_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.submit_crs_cycle(cycle_id, ADMINISTRATOR))


def record_visit(cycle_id: str, **payload) -> dict:
    return get_success_data(
        api_client.record_verification_visit(cycle_id, COORDINATOR, dict(payload) or None)
    )


def certify_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.certify_crs_cycle(cycle_id, COORDINATOR))


def lapse_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.lapse_crs_cycle(cycle_id, COORDINATOR))


def read_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_crs_cycle(cycle_id, COORDINATOR))


def setup_submitted_cycle(community_overrides=None, cycle_overrides=None,
                          standard_overrides=None) -> dict:
    """A community holding one VERIFIED credit submission, with a recertification
    cycle already SUBMITTED (claimed points and provisional class frozen)."""
    community = register_community(**(community_overrides or {}))
    standard = setup_verified_standard(community["id"], **(standard_overrides or {}))
    cycle = open_cycle(community["id"], **(cycle_overrides or {}))
    cycle = submit_cycle(cycle["id"])
    return {"community": read_community(community["id"]), "standard": standard, "cycle": cycle}
