"""Composable scenario builders.

Every builder takes an optional ``scenario`` dict, performs one workflow step
through the API, and returns the same dict extended with what it created. A test
therefore composes preconditions by chaining builders, and the tiered composites
at the bottom of this module package the chains that recur across the suite.

Because the database starts empty for every test, every builder reaches the
server only through endpoints the PRD declares.

Identity threading matters here. A ``TalentRepresentative``'s user id is the
talent's own id and an ``EstateRepresentative``'s user id is the verified estate
authority's own id, so each scenario carries freshly built headers for those two
roles rather than a shared constant.
"""

from prd_bench_local_runner.testing import validate_success

from . import factories
from .api_client import api_client
from .constants import (
    COMPLIANCE_OFFICER_ONE,
    LICENSEE_ONE,
    RIGHTS_ADMIN_ONE,
    RIGHTS_ADMIN_TWO,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_estate_representative_headers,
    make_licensee_producer_headers,
    make_rights_administrator_headers,
    make_talent_representative_headers,
)

ADMIN_HEADERS = TEST_USERS["rights_administrator_headers"]
SECOND_ADMIN_HEADERS = TEST_USERS["second_rights_administrator_headers"]
LICENSEE_HEADERS = TEST_USERS["licensee_producer_headers"]
OTHER_LICENSEE_HEADERS = TEST_USERS["other_licensee_producer_headers"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_officer_headers"]
SECOND_COMPLIANCE_HEADERS = TEST_USERS["second_compliance_officer_headers"]


def new_scenario() -> dict:
    """An empty scenario carrying the role headers every builder needs."""
    return {
        "admin_headers": ADMIN_HEADERS,
        "second_admin_headers": SECOND_ADMIN_HEADERS,
        "licensee_headers": LICENSEE_HEADERS,
        "other_licensee_headers": OTHER_LICENSEE_HEADERS,
        "compliance_headers": COMPLIANCE_HEADERS,
        "second_compliance_headers": SECOND_COMPLIANCE_HEADERS,
        "admin_user_id": RIGHTS_ADMIN_ONE,
        "second_admin_user_id": RIGHTS_ADMIN_TWO,
        "licensee_user_id": LICENSEE_ONE,
        "compliance_user_id": COMPLIANCE_OFFICER_ONE,
        "union_rows": [],
        "assets": [],
        "grants": [],
        "replicas": [],
        "performances": [],
        "licenses": [],
        "cases": [],
    }


def _scenario(scenario: dict = None) -> dict:
    return scenario if scenario is not None else new_scenario()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------


def move_clock(to_iso8601: str, headers: dict = None) -> str:
    """Move the logical clock and return the new current_utc."""
    response = api_client.set_clock(to_iso8601, headers or ADMIN_HEADERS)
    data = validate_success(response, 200)
    return data["current_utc"]


# --------------------------------------------------------------------------
# reference data
# --------------------------------------------------------------------------


def register_state_law_profile(scenario: dict = None, overrides: dict = None) -> dict:
    """Register one state law profile and remember it under ``profile``."""
    scenario = _scenario(scenario)
    payload = factories.state_law_profile_payload(**(overrides or {}))
    response = api_client.create_state_law_profile(payload, scenario["admin_headers"])
    profile = validate_success(response, 201)
    scenario.setdefault("profiles", {})[profile["state_code"]] = profile
    scenario["profile"] = profile
    return scenario


def register_union_minimum(scenario: dict = None, overrides: dict = None) -> dict:
    """Register one union minimum row and append it to ``union_rows``."""
    scenario = _scenario(scenario)
    payload = factories.union_minimum_payload(**(overrides or {}))
    response = api_client.create_union_minimum_schedule(payload, scenario["admin_headers"])
    row = validate_success(response, 201)
    scenario["union_rows"].append(row)
    scenario["union_row"] = row
    return scenario


# --------------------------------------------------------------------------
# talent, death and estate administration
# --------------------------------------------------------------------------


def create_talent(scenario: dict = None, overrides: dict = None) -> dict:
    """Create a talent and thread its representative headers into the scenario."""
    scenario = _scenario(scenario)
    payload = factories.talent_payload(**(overrides or {}))
    response = api_client.create_talent(payload, scenario["admin_headers"])
    talent = validate_success(response, 201)
    scenario["talent"] = talent
    scenario["talent_rep_headers"] = make_talent_representative_headers(talent["id"])
    return scenario


def refresh_talent(scenario: dict) -> dict:
    """Re-read the talent so the caller sees its current derived fields."""
    response = api_client.get_talent(scenario["talent"]["id"], scenario["admin_headers"])
    scenario["talent"] = validate_success(response, 200)
    return scenario


def read_talent(scenario: dict) -> dict:
    """Re-read the talent and return the fresh representation."""
    return refresh_talent(scenario)["talent"]


def record_death(scenario: dict, overrides: dict = None) -> dict:
    """Record the talent's death, running the four-hop cascade."""
    payload = factories.death_record_payload(**(overrides or {}))
    response = api_client.record_death(
        scenario["talent"]["id"], payload, scenario["admin_headers"]
    )
    scenario["talent"] = validate_success(response, 200)
    return scenario


def submit_estate_authority(scenario: dict, overrides: dict = None) -> dict:
    """File an estate authority claim against the talent."""
    payload = factories.estate_authority_payload(**(overrides or {}))
    response = api_client.submit_estate_authority(
        scenario["talent"]["id"], payload, scenario["admin_headers"]
    )
    authority = validate_success(response, 201)
    scenario["estate_authority"] = authority
    scenario.setdefault("estate_authorities", []).append(authority)
    return scenario


def verify_estate_authority(scenario: dict, headers: dict = None) -> dict:
    """Verify the filed claim with a second administrator's hands."""
    response = api_client.verify_estate_authority(
        scenario["estate_authority"]["id"],
        {},
        headers or scenario["second_admin_headers"],
    )
    authority = validate_success(response, 200)
    scenario["estate_authority"] = authority
    scenario["estate_rep_headers"] = make_estate_representative_headers(authority["id"])
    return refresh_talent(scenario)


# --------------------------------------------------------------------------
# consent grants
# --------------------------------------------------------------------------


def draft_consent_grant(scenario: dict, overrides: dict = None) -> dict:
    """Draft a grant, echoing the talent's current version at the gate.

    A draft advances the talent's version, so the talent is re-read first and
    the fresh value is echoed as ``expected_talent_version`` unless the caller
    overrides it deliberately.
    """
    refresh_talent(scenario)
    overrides = dict(overrides or {})
    if overrides.get("grantor_kind") == "ESTATE" and "estate_authority_id" not in overrides:
        overrides["estate_authority_id"] = scenario["estate_authority"]["id"]
    payload = factories.consent_grant_payload(
        scenario["talent"]["id"], scenario["talent"]["version"], **overrides
    )
    response = api_client.create_consent_grant(payload, scenario["admin_headers"])
    grant = validate_success(response, 201)
    scenario["grant"] = grant
    scenario["grants"].append(grant)
    return scenario


def refresh_grant(scenario: dict, grant: dict = None) -> dict:
    """Re-read a grant and return the fresh representation."""
    target = grant or scenario["grant"]
    response = api_client.get_consent_grant(target["id"], scenario["admin_headers"])
    fresh = validate_success(response, 200)
    if grant is None:
        scenario["grant"] = fresh
    return fresh


def grantor_headers(scenario: dict, grant: dict = None) -> dict:
    """The headers of whichever side executes the grant."""
    target = grant or scenario["grant"]
    if target["grantor_kind"] == "ESTATE":
        return scenario["estate_rep_headers"]
    return scenario["talent_rep_headers"]


def countersign_grant(scenario: dict, grant: dict = None, headers: dict = None) -> dict:
    """Countersign the grant, activating it and posting creation compensation."""
    target = grant or scenario["grant"]
    response = api_client.countersign_consent_grant(
        target["id"], {}, headers or grantor_headers(scenario, target)
    )
    fresh = validate_success(response, 200)
    if grant is None:
        scenario["grant"] = fresh
    else:
        for index, existing in enumerate(scenario["grants"]):
            if existing["id"] == fresh["id"]:
                scenario["grants"][index] = fresh
    return scenario


def suspend_grant(scenario: dict, grant: dict = None, overrides: dict = None) -> dict:
    """Suspend an active grant."""
    target = grant or scenario["grant"]
    payload = factories.suspension_payload("SUSPEND", **(overrides or {}))
    response = api_client.change_consent_grant_suspension(
        target["id"], payload, scenario["admin_headers"]
    )
    fresh = validate_success(response, 200)
    if grant is None:
        scenario["grant"] = fresh
    return fresh


def reinstate_grant(scenario: dict, grant: dict = None, overrides: dict = None) -> dict:
    """Reinstate a suspended grant."""
    target = grant or scenario["grant"]
    payload = factories.suspension_payload("REINSTATE", **(overrides or {}))
    response = api_client.change_consent_grant_suspension(
        target["id"], payload, scenario["admin_headers"]
    )
    fresh = validate_success(response, 200)
    if grant is None:
        scenario["grant"] = fresh
    return fresh


def revoke_grant(scenario: dict, grant: dict = None, headers: dict = None) -> dict:
    """Revoke the grant, running the five-hop cascade."""
    target = grant or scenario["grant"]
    response = api_client.revoke_consent_grant(
        target["id"],
        factories.revoke_payload(),
        headers or grantor_headers(scenario, target),
    )
    fresh = validate_success(response, 200)
    if grant is None:
        scenario["grant"] = fresh
    return fresh


# --------------------------------------------------------------------------
# biometric custody
# --------------------------------------------------------------------------


def register_biometric_asset(scenario: dict, overrides: dict = None) -> dict:
    """Register one captured sample under the scenario's active grant."""
    payload = factories.biometric_asset_payload(
        scenario["talent"]["id"], scenario["grant"]["id"], **(overrides or {})
    )
    response = api_client.create_biometric_asset(payload, scenario["admin_headers"])
    asset = validate_success(response, 201)
    scenario["asset"] = asset
    scenario["assets"].append(asset)
    return scenario


def refresh_asset(scenario: dict, asset: dict = None) -> dict:
    """Re-read a biometric asset and return the fresh representation."""
    target = asset or scenario["asset"]
    response = api_client.get_biometric_asset(target["id"], scenario["admin_headers"])
    fresh = validate_success(response, 200)
    if asset is None:
        scenario["asset"] = fresh
    return fresh


def purge_asset(scenario: dict, asset: dict = None) -> dict:
    """Destroy a stored sample ahead of its scheduled purge."""
    target = asset or scenario["asset"]
    response = api_client.purge_biometric_asset(
        target["id"], factories.purge_payload(), scenario["admin_headers"]
    )
    return validate_success(response, 200)


# --------------------------------------------------------------------------
# digital replicas
# --------------------------------------------------------------------------


def build_replica(scenario: dict, overrides: dict = None, source_asset_ids=None) -> dict:
    """Train a replica from the scenario's stored samples."""
    sources = source_asset_ids or [asset["id"] for asset in scenario["assets"]]
    payload = factories.digital_replica_payload(
        scenario["talent"]["id"], scenario["grant"]["id"], sources, **(overrides or {})
    )
    response = api_client.create_digital_replica(payload, scenario["admin_headers"])
    replica = validate_success(response, 201)
    scenario["replica"] = replica
    scenario["replicas"].append(replica)
    return scenario


def refresh_replica(scenario: dict, replica: dict = None) -> dict:
    """Re-read a replica and return the fresh representation."""
    target = replica or scenario["replica"]
    response = api_client.get_digital_replica(target["id"], scenario["admin_headers"])
    fresh = validate_success(response, 200)
    if replica is None:
        scenario["replica"] = fresh
    return fresh


def approve_replica(scenario: dict, replica: dict = None, headers: dict = None) -> dict:
    """Record the talent-side approval that the replica may be exploited."""
    target = replica or scenario["replica"]
    response = api_client.approve_replica_for_use(
        target["id"],
        factories.approve_replica_payload(),
        headers or grantor_headers(scenario),
    )
    fresh = validate_success(response, 200)
    if replica is None:
        scenario["replica"] = fresh
    return scenario


# --------------------------------------------------------------------------
# generated performances
# --------------------------------------------------------------------------


def submit_performance(
    scenario: dict, overrides: dict = None, replica: dict = None, headers: dict = None
) -> dict:
    """Submit a generated performance, accruing the provisional royalty."""
    target = replica or scenario["replica"]
    payload = factories.generated_performance_payload(target["id"], **(overrides or {}))
    response = api_client.create_generated_performance(
        payload, headers or scenario["licensee_headers"]
    )
    performance = validate_success(response, 201)
    scenario["performance"] = performance
    scenario["performances"].append(performance)
    return scenario


def refresh_performance(scenario: dict, performance: dict = None) -> dict:
    """Re-read a performance and return the fresh representation."""
    target = performance or scenario["performance"]
    response = api_client.get_generated_performance(target["id"], scenario["admin_headers"])
    fresh = validate_success(response, 200)
    if performance is None:
        scenario["performance"] = fresh
    return fresh


def review_performance(
    scenario: dict,
    decision: str = "APPROVE",
    overrides: dict = None,
    performance: dict = None,
    headers: dict = None,
) -> dict:
    """Record a review decision from the talent's side of the table."""
    target = performance or scenario["performance"]
    payload = factories.review_payload(decision, **(overrides or {}))
    response = api_client.review_generated_performance(
        target["id"], payload, headers or grantor_headers(scenario)
    )
    fresh = validate_success(response, 200)
    if performance is None:
        scenario["performance"] = fresh
    return fresh


def resubmit_performance(
    scenario: dict, overrides: dict = None, performance: dict = None, headers: dict = None
) -> dict:
    """Resubmit a revision-requested performance with fresh projections."""
    target = performance or scenario["performance"]
    payload = factories.resubmit_payload(**(overrides or {}))
    response = api_client.resubmit_generated_performance(
        target["id"], payload, headers or scenario["licensee_headers"]
    )
    fresh = validate_success(response, 200)
    if performance is None:
        scenario["performance"] = fresh
    return fresh


# --------------------------------------------------------------------------
# usage licenses
# --------------------------------------------------------------------------


def issue_license(
    scenario: dict, overrides: dict = None, performance: dict = None, headers: dict = None
) -> dict:
    """Issue a license, echoing the replica's current version at the gate."""
    target = performance or scenario["performance"]
    replica = refresh_replica(scenario)
    overrides = dict(overrides or {})
    expected_version = overrides.pop("expected_replica_version", replica["version"])
    payload = factories.usage_license_payload(
        target["id"], expected_version, **overrides
    )
    response = api_client.create_usage_license(
        payload, headers or scenario["licensee_headers"]
    )
    license_row = validate_success(response, 201)
    scenario["license"] = license_row
    scenario["licenses"].append(license_row)
    return scenario


def refresh_license(scenario: dict, license_row: dict = None) -> dict:
    """Re-read a license and return the fresh representation."""
    target = license_row or scenario["license"]
    response = api_client.get_usage_license(target["id"], scenario["admin_headers"])
    fresh = validate_success(response, 200)
    if license_row is None:
        scenario["license"] = fresh
    return fresh


def attest_disclosure(
    scenario: dict, overrides: dict = None, license_row: dict = None, headers: dict = None
) -> dict:
    """Attest the synthetic-content disclosure label and its placement."""
    target = license_row or scenario["license"]
    payload = factories.disclosure_payload(**(overrides or {}))
    response = api_client.attest_disclosure(
        target["id"], payload, headers or scenario["licensee_headers"]
    )
    fresh = validate_success(response, 200)
    if license_row is None:
        scenario["license"] = fresh
    return fresh


def verify_disclosure(
    scenario: dict, decision: str = "ACCEPT", license_row: dict = None, headers: dict = None
) -> dict:
    """Accept or reject an attested disclosure."""
    target = license_row or scenario["license"]
    payload = factories.disclosure_verification_payload(decision)
    response = api_client.verify_disclosure(
        target["id"], payload, headers or scenario["compliance_headers"]
    )
    fresh = validate_success(response, 200)
    if license_row is None:
        scenario["license"] = fresh
    return fresh


def go_live(
    scenario: dict, overrides: dict = None, license_row: dict = None, headers: dict = None
) -> dict:
    """Begin distribution of the licensed synthetic content."""
    target = license_row or scenario["license"]
    payload = factories.go_live_payload(**(overrides or {}))
    response = api_client.go_live(
        target["id"], payload, headers or scenario["licensee_headers"]
    )
    fresh = validate_success(response, 200)
    if license_row is None:
        scenario["license"] = fresh
    return fresh


def confirm_removal(scenario: dict, license_row: dict = None, headers: dict = None) -> dict:
    """Confirm that distributed content has been pulled down."""
    target = license_row or scenario["license"]
    response = api_client.confirm_removal(
        target["id"],
        factories.confirm_removal_payload(),
        headers or scenario["licensee_headers"],
    )
    fresh = validate_success(response, 200)
    if license_row is None:
        scenario["license"] = fresh
    return fresh


# --------------------------------------------------------------------------
# infringement cases
# --------------------------------------------------------------------------


def open_case(scenario: dict, overrides: dict = None, headers: dict = None) -> dict:
    """Open a suspected unauthorized-use case from a monitoring hit."""
    payload = factories.infringement_case_payload(
        scenario["talent"]["id"], **(overrides or {})
    )
    response = api_client.create_infringement_case(
        payload, headers or scenario["compliance_headers"]
    )
    case = validate_success(response, 201)
    scenario["case"] = case
    scenario["cases"].append(case)
    return scenario


def refresh_case(scenario: dict, case: dict = None) -> dict:
    """Re-read a case and return the fresh representation."""
    target = case or scenario["case"]
    response = api_client.get_infringement_case(target["id"], scenario["compliance_headers"])
    fresh = validate_success(response, 200)
    if case is None:
        scenario["case"] = fresh
    return fresh


def triage_case(
    scenario: dict, decision: str = "ISSUE_TAKEDOWN", case: dict = None, headers: dict = None
) -> dict:
    """Triage a detected case: dismiss it, or issue a takedown."""
    target = case or scenario["case"]
    payload = factories.triage_payload(decision)
    response = api_client.triage_infringement_case(
        target["id"], payload, headers or scenario["compliance_headers"]
    )
    fresh = validate_success(response, 200)
    if case is None:
        scenario["case"] = fresh
    return fresh


def escalate_case(scenario: dict, case: dict = None, headers: dict = None) -> dict:
    """Escalate an issued takedown to legal, impounding the talent's material.

    The escalating administrator must not be the officer who triaged the case,
    so the second administrator's headers are the default here.
    """
    target = case or scenario["case"]
    response = api_client.escalate_infringement_case(
        target["id"],
        factories.escalate_payload(),
        headers or scenario["second_admin_headers"],
    )
    fresh = validate_success(response, 200)
    if case is None:
        scenario["case"] = fresh
    return fresh


def close_case(
    scenario: dict, outcome: str = "REMOVED", case: dict = None, headers: dict = None
) -> dict:
    """Close a case, releasing any legal holds it applied."""
    target = case or scenario["case"]
    payload = factories.close_case_payload(outcome)
    response = api_client.close_infringement_case(
        target["id"], payload, headers or scenario["admin_headers"]
    )
    fresh = validate_success(response, 200)
    if case is None:
        scenario["case"] = fresh
    return fresh


# --------------------------------------------------------------------------
# ops run and ledger reads
# --------------------------------------------------------------------------


def run_sweep(scenario: dict = None, headers: dict = None) -> dict:
    """Run the five-phase compliance sweep and return its report."""
    scenario = _scenario(scenario)
    response = api_client.run_compliance_sweep(headers or scenario["admin_headers"])
    return validate_success(response, 200)


def ledger_entries(scenario: dict, params: dict = None) -> list:
    """Read the ledger, optionally filtered, in posted_at ascending order."""
    from prd_bench_local_runner.testing import validate_paginated

    response = api_client.list_compensation_entries(
        scenario["admin_headers"], params=params
    )
    data, _meta = validate_paginated(response)
    return data


def grant_ledger(scenario: dict, grant: dict = None) -> list:
    """Every ledger entry raised under one grant."""
    target = grant or scenario["grant"]
    return ledger_entries(scenario, {"consent_grant_id": target["id"], "limit": 100})


def talent_ledger(scenario: dict) -> list:
    """Every ledger entry belonging to the scenario's talent."""
    return ledger_entries(scenario, {"talent_id": scenario["talent"]["id"], "limit": 100})


# --------------------------------------------------------------------------
# tiered composites — the chains the suite reuses
# --------------------------------------------------------------------------


def setup_reference_data(profile_overrides: dict = None, union_rows: list = None) -> dict:
    """Tier 1: the external law this office must obey.

    Registers one state law profile and, when asked, one union minimum row per
    entry in ``union_rows``.
    """
    scenario = register_state_law_profile(new_scenario(), profile_overrides)
    for row_overrides in union_rows or []:
        register_union_minimum(scenario, row_overrides)
    return scenario


def setup_talent(
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 2: reference data plus one living talent."""
    scenario = setup_reference_data(profile_overrides, union_rows)
    return create_talent(scenario, talent_overrides)


def setup_deceased_talent_with_verified_estate(
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
    death_overrides: dict = None,
    authority_overrides: dict = None,
) -> dict:
    """Tier 2: a talent recorded dead whose estate authority is verified.

    Verification is a second administrator's act, so the filer and the verifier
    are deliberately different users.
    """
    scenario = setup_talent(talent_overrides, profile_overrides, union_rows)
    record_death(scenario, death_overrides)
    submit_estate_authority(scenario, authority_overrides)
    return verify_estate_authority(scenario)


def setup_drafted_grant(
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 3: a grant sitting in PENDING_COUNTERSIGN."""
    scenario = setup_talent(talent_overrides, profile_overrides, union_rows)
    return draft_consent_grant(scenario, grant_overrides)


def setup_active_grant(
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 3: a countersigned, ACTIVE grant with its creation payment posted."""
    scenario = setup_drafted_grant(
        grant_overrides, talent_overrides, profile_overrides, union_rows
    )
    return countersign_grant(scenario)


def setup_stored_asset(
    asset_overrides: dict = None,
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 4: one captured sample in STORED custody under an active grant."""
    scenario = setup_active_grant(
        grant_overrides, talent_overrides, profile_overrides, union_rows
    )
    return register_biometric_asset(scenario, asset_overrides)


def setup_built_replica(
    replica_overrides: dict = None,
    asset_overrides: dict = None,
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 5: a replica in BUILT status trained from that one sample."""
    scenario = setup_stored_asset(
        asset_overrides, grant_overrides, talent_overrides, profile_overrides, union_rows
    )
    return build_replica(scenario, replica_overrides)


def setup_approved_replica(
    replica_overrides: dict = None,
    asset_overrides: dict = None,
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 5: a replica the talent's side has approved for use."""
    scenario = setup_built_replica(
        replica_overrides,
        asset_overrides,
        grant_overrides,
        talent_overrides,
        profile_overrides,
        union_rows,
    )
    return approve_replica(scenario)


def setup_submitted_performance(
    performance_overrides: dict = None,
    replica_overrides: dict = None,
    asset_overrides: dict = None,
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 6: a performance in SUBMITTED with its provisional accrual posted."""
    scenario = setup_approved_replica(
        replica_overrides,
        asset_overrides,
        grant_overrides,
        talent_overrides,
        profile_overrides,
        union_rows,
    )
    return submit_performance(scenario, performance_overrides)


def setup_approved_performance(
    performance_overrides: dict = None,
    replica_overrides: dict = None,
    asset_overrides: dict = None,
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 6: a performance the talent's side approved, accrual retained."""
    scenario = setup_submitted_performance(
        performance_overrides,
        replica_overrides,
        asset_overrides,
        grant_overrides,
        talent_overrides,
        profile_overrides,
        union_rows,
    )
    review_performance(scenario, "APPROVE")
    return scenario


def setup_issued_license(
    license_overrides: dict = None,
    performance_overrides: dict = None,
    replica_overrides: dict = None,
    asset_overrides: dict = None,
    grant_overrides: dict = None,
    talent_overrides: dict = None,
    profile_overrides: dict = None,
    union_rows: list = None,
) -> dict:
    """Tier 7: a license in ISSUED with its final royalty and total assembled."""
    scenario = setup_approved_performance(
        performance_overrides,
        replica_overrides,
        asset_overrides,
        grant_overrides,
        talent_overrides,
        profile_overrides,
        union_rows,
    )
    return issue_license(scenario, license_overrides)


def setup_verified_disclosure_license(
    license_overrides: dict = None,
    disclosure_overrides: dict = None,
    **kwargs,
) -> dict:
    """Tier 7: an ISSUED license whose disclosure has been attested and accepted."""
    scenario = setup_issued_license(license_overrides, **kwargs)
    attest_disclosure(scenario, disclosure_overrides)
    verify_disclosure(scenario, "ACCEPT")
    return scenario


def setup_live_license(
    go_live_at: str = "2026-09-01T00:00:00Z",
    license_overrides: dict = None,
    disclosure_overrides: dict = None,
    **kwargs,
) -> dict:
    """Tier 7: a LIVE license.

    Going live requires the logical clock to sit inside the closed distribution
    window, so the clock is moved to ``go_live_at`` before the transition and is
    left there for the caller.
    """
    scenario = setup_verified_disclosure_license(
        license_overrides, disclosure_overrides, **kwargs
    )
    move_clock(go_live_at, scenario["admin_headers"])
    go_live(scenario)
    return scenario


def setup_takedown_issued_case(
    case_overrides: dict = None,
    scenario: dict = None,
    **kwargs,
) -> dict:
    """Tier 8: a case in TAKEDOWN_ISSUED over the scenario's talent."""
    scenario = scenario if scenario is not None else setup_stored_asset(**kwargs)
    open_case(scenario, case_overrides)
    triage_case(scenario, "ISSUE_TAKEDOWN")
    return scenario


def setup_escalated_case(
    case_overrides: dict = None,
    scenario: dict = None,
    **kwargs,
) -> dict:
    """Tier 8: a case in LEGAL_ESCALATED, with the talent's material impounded.

    The default detection is confident enough and reaches far enough to clear the
    mandatory-takedown threshold, so the takedown is the only permitted fork and
    the escalation floor is comfortably cleared.
    """
    overrides = {"match_confidence": 1.0, "detected_view_count": 10_000_000}
    overrides.update(case_overrides or {})
    scenario = setup_takedown_issued_case(overrides, scenario, **kwargs)
    escalate_case(scenario)
    refresh_talent(scenario)
    return scenario


# --------------------------------------------------------------------------
# the union voice-campaign chain
#
# One negotiated shape recurs across the suite: a SAG_AFTRA performer domiciled
# in a seventy-year state, a one-year non-exclusive advertising grant over two
# territories at 300000 / 150000, a voice sample, a voice replica, an
# advertising output projecting six million impressions and a license
# delivering twelve million across both territories. The dictionaries below
# hold that shape so a test states only its own departures from it.
# --------------------------------------------------------------------------

CAMPAIGN_PROFILE = {"biometric_retention_max_days": 365}

SAG_ADVERTISING_ROW = {
    "union_code": "SAG_AFTRA",
    "media_type": "ADVERTISING",
    "effective_from": "2026-07-01T00:00:00Z",
    "minimum_initial_cents": 300_000,
    "minimum_per_use_cents": 150_000,
}

CAMPAIGN_TALENT = {"legal_name": "Ava Reyes", "union_code": "SAG_AFTRA"}

CAMPAIGN_GRANT = {
    "permitted_media_types": ["ADVERTISING"],
    "territory_codes": ["US", "MX"],
    "permitted_use_notes": "National voice campaign",
    "exclusivity": "NON_EXCLUSIVE",
    "effective_from": "2026-08-01T00:00:00Z",
    "effective_until": "2027-08-01T00:00:00Z",
    "initial_creation_fee_cents": 300_000,
    "per_use_base_fee_cents": 150_000,
}

CAMPAIGN_ASSET = {
    "asset_kind": "VOICE_SAMPLE",
    "capture_ref": "cap-001",
    "storage_class": "ENCRYPTED_VAULT",
    "payload_digest": "sha256:aaa",
}

CAMPAIGN_REPLICA = {"replica_kind": "VOICE", "build_ref": "build-001"}

CAMPAIGN_PERFORMANCE = {
    "licensee_name": "Northwind Ads",
    "media_type": "ADVERTISING",
    "territory_codes": ["US", "MX"],
    "intended_use_description": "30 second radio spot",
    "projected_impressions": 6_000_000,
    "scheduled_first_use_at": "2026-09-01T00:00:00Z",
}

CAMPAIGN_LICENSE = {
    "channel": "ADVERTISING",
    "territory_codes": ["US", "MX"],
    "distribution_start": "2026-09-01T00:00:00Z",
    "distribution_end": "2027-06-01T00:00:00Z",
    "actual_impressions": 12_000_000,
}


def _merged(base: dict, overrides: dict = None) -> dict:
    merged = dict(base)
    merged.update(overrides or {})
    return merged


def campaign_active_grant(profile_overrides: dict = None, grant_overrides: dict = None) -> dict:
    """The campaign chain up to an ACTIVE grant with its creation payment posted."""
    return setup_active_grant(
        grant_overrides=_merged(CAMPAIGN_GRANT, grant_overrides),
        talent_overrides=CAMPAIGN_TALENT,
        profile_overrides=_merged(CAMPAIGN_PROFILE, profile_overrides),
        union_rows=[SAG_ADVERTISING_ROW],
    )


def campaign_stored_asset(
    profile_overrides: dict = None,
    grant_overrides: dict = None,
    asset_overrides: dict = None,
) -> dict:
    """The campaign chain up to one voice sample in STORED custody."""
    scenario = campaign_active_grant(profile_overrides, grant_overrides)
    return register_biometric_asset(scenario, _merged(CAMPAIGN_ASSET, asset_overrides))


def campaign_built_replica(
    profile_overrides: dict = None,
    grant_overrides: dict = None,
    asset_overrides: dict = None,
    replica_overrides: dict = None,
) -> dict:
    """The campaign chain up to a replica in BUILT."""
    scenario = campaign_stored_asset(profile_overrides, grant_overrides, asset_overrides)
    return build_replica(scenario, _merged(CAMPAIGN_REPLICA, replica_overrides))


def campaign_approved_replica(
    profile_overrides: dict = None,
    grant_overrides: dict = None,
    asset_overrides: dict = None,
    replica_overrides: dict = None,
) -> dict:
    """The campaign chain up to a replica in APPROVED_FOR_USE."""
    scenario = campaign_built_replica(
        profile_overrides, grant_overrides, asset_overrides, replica_overrides
    )
    return approve_replica(scenario)


def campaign_submitted_performance(
    performance_overrides: dict = None,
    profile_overrides: dict = None,
    grant_overrides: dict = None,
    asset_overrides: dict = None,
    replica_overrides: dict = None,
) -> dict:
    """The campaign chain up to a SUBMITTED output with its provisional accrual."""
    scenario = campaign_approved_replica(
        profile_overrides, grant_overrides, asset_overrides, replica_overrides
    )
    return submit_performance(scenario, _merged(CAMPAIGN_PERFORMANCE, performance_overrides))


def campaign_approved_performance(
    performance_overrides: dict = None,
    profile_overrides: dict = None,
    grant_overrides: dict = None,
    asset_overrides: dict = None,
    replica_overrides: dict = None,
) -> dict:
    """The campaign chain up to an APPROVED output, accrual retained."""
    scenario = campaign_submitted_performance(
        performance_overrides, profile_overrides, grant_overrides, asset_overrides,
        replica_overrides,
    )
    review_performance(scenario, "APPROVE", {"review_note": "sounds right"})
    return scenario


def campaign_issued_license(
    license_overrides: dict = None,
    performance_overrides: dict = None,
    profile_overrides: dict = None,
    grant_overrides: dict = None,
    asset_overrides: dict = None,
    replica_overrides: dict = None,
) -> dict:
    """The campaign chain up to an ISSUED license."""
    scenario = campaign_approved_performance(
        performance_overrides, profile_overrides, grant_overrides, asset_overrides,
        replica_overrides,
    )
    return issue_license(scenario, _merged(CAMPAIGN_LICENSE, license_overrides))


def campaign_live_license(
    go_live_at: str = "2026-09-01T00:00:00Z",
    license_overrides: dict = None,
    **kwargs,
) -> dict:
    """The campaign chain up to a LIVE license with a verified PRE_ROLL disclosure."""
    scenario = campaign_issued_license(license_overrides, **kwargs)
    attest_disclosure(
        scenario,
        {
            "disclosure_placement": "PRE_ROLL",
            "disclosure_label_text": (
                "Voice generated with the artist's licensed digital replica"
            ),
        },
    )
    verify_disclosure(scenario, "ACCEPT")
    move_clock(go_live_at, scenario["admin_headers"])
    go_live(scenario, {"distribution_reference": "spot-ref-001"})
    return scenario
