"""Corner — state_machines section.

Auto-transitions, invalid transitions, idempotency, side-effect cascades,
precondition enforcement, and terminal-state lockdown on RegisteredAgent.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_forming_business_entity,
    create_registered_agent_for,
    create_and_execute_operating_agreement,
    create_and_issue_ein,
    setup_active_llc,
    create_draft_annual_report,
    create_foreign_agent,
    create_pending_foreign_qualification,
    approve_foreign_qualification,
    make_filer_headers,
    make_state_admin_headers,
    make_compliance_officer_headers,
)


def test_business_entity_auto_to_active_on_complete_formation_chain(api):
    """PRD §3.2: "The transition from `FORMING` to `ACTIVE` is automatic and
    posture-shaped. The system advances the `BusinessEntity` from `FORMING` to
    `ACTIVE` the moment three conditions hold simultaneously: there is exactly
    one `RegisteredAgent` in `ACTIVE` status for the entity; there is exactly one
    `EINApplication` in `ISSUED` status for the entity; and, if the `entity_type`
    is `LLC` or `LP`, at least one `OperatingAgreement` for the entity is in
    `EXECUTED` status."

    Design: Corner/state_machines/business_entity_auto_to_active_on_complete_formation_chain
    """
    set_clock("2026-01-01T00:00:00Z")
    be = create_forming_business_entity(
        legal_name="JULIET LLC", entity_type="LLC", formation_state_code="DE"
    )
    assert be["status"] == "FORMING"
    create_registered_agent_for(be)
    create_and_execute_operating_agreement(be)
    create_and_issue_ein(be)
    after = validate_success(
        api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
    )
    assert after["status"] == "ACTIVE"


def test_dissolve_dissolved_entity_returns_invalid_state(api):
    """PRD §3.12: "Voluntary dissolution is the filer's path to ending the entity.
    The dissolve call is only legal when the entity's `status` is `ACTIVE` or
    `DELINQUENT` and no `ForeignQualification` for the entity is in `QUALIFIED`"

    Design: Corner/state_machines/dissolve_dissolved_entity_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    be, _ = setup_active_llc(legal_name="KILO LLC", formation_state_code="DE")
    api.dissolve_business_entity(be["id"], make_filer_headers(be["id"]))
    # Second dissolve attempt on a DISSOLVED entity — state precondition is
    # violated. PRD §2.10 orders ERR_INVALID_STATE (P40) before the dissolved
    # gate (P45), so the state error surfaces.
    res = api.dissolve_business_entity(be["id"], make_filer_headers(be["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_ein_application_idempotent_issue_after_issued_fails(api):
    """PRD §3.5: "Both `ISSUED` and `REJECTED` are terminal — the application
    cannot be re-acted on."

    Design: Corner/state_machines/ein_application_idempotent_issue_after_issued_fails
    """
    set_clock("2026-01-01T00:00:00Z")
    be = create_forming_business_entity(
        legal_name="LIMA LLC", entity_type="LLC", formation_state_code="DE"
    )
    create_registered_agent_for(be)
    ein_app = create_and_issue_ein(be)
    assert ein_app["status"] == "ISSUED"
    res = api.issue_ein_application(ein_app["id"], make_state_admin_headers())
    validate_error(res, "ERR_INVALID_STATE")


def test_cascade_dissolve_voids_drafts_and_resigns_agents(api):
    """PRD §3.12: "On a legal dissolve, the parent's `status` transitions to
    `DISSOLVED`, the `compliance_posture` is reset to `FROZEN`, every
    `AnnualReport` in `DRAFT` or `DELINQUENT` is flipped to `VOIDED`, every
    `RegisteredAgent` in `ACTIVE` is flipped to `RESIGNED`"

    Design: Corner/state_machines/cascade_dissolve_voids_drafts_and_resigns_agents
    """
    set_clock("2025-03-01T00:00:00Z")
    be, ra = setup_active_llc(legal_name="MIKE LLC", formation_state_code="DE")
    ar = create_draft_annual_report(be, 2024)
    api.dissolve_business_entity(be["id"], make_filer_headers(be["id"]))
    ra_after = validate_success(
        api.get_registered_agent(ra["id"], make_compliance_officer_headers()), 200
    )
    ar_list = validate_success(
        api.list_annual_reports(be["id"], make_compliance_officer_headers()), 200
    )
    be_after = validate_success(
        api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
    )
    assert ra_after["status"] == "RESIGNED"
    matching = [r for r in ar_list if r["id"] == ar["id"]]
    assert matching and matching[0]["status"] == "VOIDED"
    assert be_after["compliance_posture"] == "FROZEN"


def test_foreign_qualification_blocks_dissolution(api):
    """PRD §3.12: "The dissolve call is only legal when the entity's `status` is
    `ACTIVE` or `DELINQUENT` and no `ForeignQualification` for the entity is in
    `QUALIFIED` — an outstanding foreign qualification blocks dissolution and
    must be withdrawn first."

    Design: Corner/state_machines/foreign_qualification_blocks_dissolution
    """
    set_clock("2025-03-01T00:00:00Z")
    be, _ = setup_active_llc(legal_name="NOV LLC", formation_state_code="DE")
    foreign_agent = create_foreign_agent(be, foreign_state_code="CA")
    fq = create_pending_foreign_qualification(be, "CA", foreign_agent["id"])
    approve_foreign_qualification(fq["id"])
    res = api.dissolve_business_entity(be["id"], make_filer_headers(be["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_reinstate_from_active_returns_invalid_state(api):
    """PRD §3.2: "a `SUSPENDED` entity can be reinstated to `ACTIVE` by a
    `StateAdmin`"

    Design: Corner/state_machines/reinstate_from_active_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    be, _ = setup_active_llc(legal_name="OSCAR LLC", formation_state_code="DE")
    # Entity is ACTIVE, not SUSPENDED → reinstate's state precondition fails.
    res = api.reinstate_business_entity(be["id"], make_state_admin_headers())
    validate_error(res, "ERR_INVALID_STATE")


def test_registered_agent_resign_when_resigned_invalid_state(api):
    """PRD §3.3: "Status begins at `ACTIVE` and the terminal state is `RESIGNED`."
    PRD §3.3: "A `Filer` can resign a `RegisteredAgent`; the resource transitions
    from `ACTIVE` to `RESIGNED`"

    Design: Corner/state_machines/registered_agent_resign_when_resigned_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    be, ra = setup_active_llc(legal_name="PAPA LLC", formation_state_code="DE")
    api.resign_registered_agent(ra["id"], make_filer_headers(be["id"]))
    # Second resign — terminal-state lockdown.
    res = api.resign_registered_agent(ra["id"], make_filer_headers(be["id"]))
    validate_error(res, "ERR_INVALID_STATE")
