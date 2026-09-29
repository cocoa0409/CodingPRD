"""Scenario builders for the Pentest Assurance API.

Almost every behaviour in this domain sits behind the same authorisation chain:
an asset must exist, a test plan must admit it through an approved scope item and
be activated, an engagement must be opened against that scope item, a rules-of-
engagement document must be drafted and counter-signed, an authorized target must
carve out a window, and a background-checked tester must be assigned and
provisioned before execution can start.

``build_scenario`` walks that chain once and stops wherever the caller asks, so a
test that only needs a drafted document does not pay for a running engagement, and
a test that needs the whole thing does not repeat twenty calls. Every guarded POST
re-reads its parent's ``version`` immediately beforehand and no superfluous
mutating call is made, because several tests assert exact version numbers.
"""

from . import factories
from .assertions import created_data, success_data
from .constants import T_BEFORE_ASSIGNMENT, T_PROGRAMME_OPEN
from .test_users import (
    CO_ALT_USER_ID,
    compliance_officer_headers,
    make_tester_headers,
    program_manager_headers,
)
from .types import Scenario

# The chain, in the order the server requires it.
STAGES = (
    "asset",
    "plan",
    "scope_item",
    "plan_active",
    "engagement",
    "roe",
    "targets",
    "roe_signed",
    "tester",
    "tester_cleared",
    "assignment",
    "provisioned",
    "executing",
)


def _stage_index(stage):
    assert stage in STAGES, f"unknown scenario stage {stage!r}; expected one of {STAGES}"
    return STAGES.index(stage)


def advance_clock(client, to_iso8601):
    """Move the simulated clock and return the instant it now reports."""
    success_data(client.set_clock(to_iso8601))
    return to_iso8601


def engagement_version(client, engagement_id, headers=None):
    """Read the engagement's current version token without mutating anything."""
    engagement = success_data(client.get_engagement(engagement_id, headers=headers))
    return engagement["version"]


def read_plan_version(client, plan_id, headers=None):
    """Read the test plan's current version token without mutating anything."""
    plan = success_data(client.get_test_plan(plan_id, headers=headers))
    return plan["version"]


def build_scenario(
    client,
    stage="executing",
    open_clock=T_PROGRAMME_OPEN,
    asset=None,
    plan=None,
    scope_item=None,
    decision_note="In scope for FY2026",
    engagement=None,
    roe=None,
    target=None,
    extra_targets=(),
    sign_roe=True,
    sign_note="Authorized for FY2026 window",
    tester=None,
    background_check_result="CLEARED",
    pre_assignment_clock=T_BEFORE_ASSIGNMENT,
    assignment=None,
    granted_asset_ids=None,
):
    """Walk the authorisation chain up to ``stage`` and return everything created.

    Each keyword that names an entity takes a dict of overrides for that entity's
    factory, so a caller can change one field without restating the payload.
    """
    limit = _stage_index(stage)
    scenario = Scenario()
    pm = program_manager_headers()

    advance_clock(client, open_clock)

    # --- the asset under test -------------------------------------------------
    asset_row = created_data(client.create_asset(factories.asset_payload(**(asset or {}))))
    scenario["asset"] = asset_row
    scenario["asset_id"] = asset_row["id"]
    if limit == _stage_index("asset"):
        return scenario

    # --- the annual test plan -------------------------------------------------
    plan_row = created_data(client.create_test_plan(factories.test_plan_payload(**(plan or {}))))
    scenario["plan"] = plan_row
    scenario["plan_id"] = plan_row["id"]
    if limit == _stage_index("plan"):
        return scenario

    # --- admission of the asset into the plan ---------------------------------
    scope_row = created_data(
        client.create_scope_item(
            factories.scope_item_payload(
                plan_row["id"], asset_row["id"], plan_row["version"], **(scope_item or {})
            )
        )
    )
    scope_row = success_data(
        client.decide_scope_item(
            scope_row["id"], factories.decision_payload("APPROVE", note=decision_note)
        )
    )
    scenario["scope_item"] = scope_row
    scenario["scope_item_id"] = scope_row["id"]
    if limit == _stage_index("scope_item"):
        return scenario

    # --- activation freezes the plan for the fiscal year ----------------------
    scenario["plan"] = success_data(client.activate_test_plan(plan_row["id"]))
    if limit == _stage_index("plan_active"):
        return scenario

    # --- the engagement -------------------------------------------------------
    engagement_row = created_data(
        client.create_engagement(
            factories.engagement_payload(plan_row["id"], scope_row["id"], **(engagement or {}))
        )
    )
    scenario["engagement"] = engagement_row
    scenario["engagement_id"] = engagement_row["id"]
    if limit == _stage_index("engagement"):
        return scenario

    # --- the rules of engagement ---------------------------------------------
    roe_row = created_data(
        client.create_rules_of_engagement(
            factories.rules_of_engagement_payload(engagement_row["id"], **(roe or {}))
        )
    )
    scenario["roe"] = roe_row
    scenario["roe_id"] = roe_row["id"]
    if limit == _stage_index("roe"):
        return scenario

    # --- the authorized targets ----------------------------------------------
    target_rows = []
    for overrides in [target or {}] + [dict(extra) for extra in extra_targets]:
        target_asset_id = overrides.pop("asset_id", asset_row["id"])
        target_rows.append(
            created_data(
                client.create_authorized_target(
                    factories.authorized_target_payload(
                        roe_row["id"], target_asset_id, **overrides
                    )
                )
            )
        )
    scenario["targets"] = target_rows
    scenario["target"] = target_rows[0]
    scenario["target_id"] = target_rows[0]["id"]
    if limit == _stage_index("targets"):
        return scenario

    # --- the counter-signature ------------------------------------------------
    if sign_roe:
        scenario["roe"] = success_data(
            client.sign_rules_of_engagement(roe_row["id"], signature_note=sign_note)
        )
    if limit == _stage_index("roe_signed"):
        scenario["engagement"] = success_data(
            client.get_engagement(engagement_row["id"], headers=pm)
        )
        return scenario

    # --- the tester -----------------------------------------------------------
    tester_row = created_data(client.create_tester(factories.tester_payload(**(tester or {}))))
    scenario["tester"] = tester_row
    scenario["tester_id"] = tester_row["id"]
    scenario["tester_headers"] = make_tester_headers(tester_row["id"])
    if limit == _stage_index("tester"):
        return scenario

    # --- the background check -------------------------------------------------
    if background_check_result is not None:
        scenario["tester"] = success_data(
            client.record_background_check(tester_row["id"], background_check_result)
        )
    if limit == _stage_index("tester_cleared"):
        return scenario

    # --- the assignment -------------------------------------------------------
    if pre_assignment_clock is not None:
        advance_clock(client, pre_assignment_clock)
    assignment_row = created_data(
        client.create_tester_assignment(
            factories.tester_assignment_payload(
                engagement_row["id"],
                tester_row["id"],
                engagement_version(client, engagement_row["id"], headers=pm),
                granted_asset_ids or [asset_row["id"]],
                **(assignment or {}),
            )
        )
    )
    scenario["assignment"] = assignment_row
    scenario["assignment_id"] = assignment_row["id"]
    if limit == _stage_index("assignment"):
        scenario["engagement"] = success_data(
            client.get_engagement(engagement_row["id"], headers=pm)
        )
        return scenario

    # --- provisioning the tester's access ------------------------------------
    scenario["assignment"] = success_data(
        client.set_access(assignment_row["id"], "PROVISION")
    )
    if limit == _stage_index("provisioned"):
        scenario["engagement"] = success_data(
            client.get_engagement(engagement_row["id"], headers=pm)
        )
        scenario["tester"] = success_data(client.get_tester(tester_row["id"], headers=pm))
        return scenario

    # --- fieldwork begins -----------------------------------------------------
    scenario["engagement"] = success_data(
        client.drive_execution(engagement_row["id"], "START")
    )
    scenario["tester"] = success_data(client.get_tester(tester_row["id"], headers=pm))
    return scenario


def report_finding(client, scenario, secondary=False, **overrides):
    """Report a finding as the assigned tester, threading the engagement version."""
    headers = scenario["tester_headers"]
    asset_id = overrides.pop("asset_id", scenario["asset_id"])
    version = overrides.pop(
        "expected_engagement_version",
        engagement_version(client, scenario["engagement_id"], headers=headers),
    )
    factory = factories.secondary_finding_payload if secondary else factories.finding_payload
    payload = factory(scenario["engagement_id"], asset_id, version, **overrides)
    return created_data(client.create_finding(payload, headers))


def accept_finding(client, finding_id, note="Confirmed by platform team", headers=None):
    """Triage a reported finding as a genuine issue worth remediating."""
    return success_data(
        client.triage_finding(
            finding_id, factories.triage_payload("ACCEPT", note=note), headers=headers
        )
    )


def open_remediation(client, finding_id, **overrides):
    """Open a remediation record against an accepted finding."""
    return created_data(
        client.create_remediation(factories.remediation_payload(finding_id, **overrides))
    )


def submit_evidence(client, remediation_id,
                    evidence_uri="s3://evidence/rem1/config-diff.txt", headers=None):
    """Submit remediation evidence as the remediation owner."""
    return success_data(
        client.submit_remediation(remediation_id, evidence_uri, headers=headers)
    )


def open_retest(client, remediation_id, headers=None, **overrides):
    """Record a retest verification as a compliance officer other than the signer."""
    return created_data(
        client.create_retest_verification(
            factories.retest_verification_payload(remediation_id, **overrides),
            headers if headers is not None else compliance_officer_headers(CO_ALT_USER_ID),
        )
    )
