"""Transitions that are legal only while a sibling row sits in the right state."""
from test_helpers import (
    AGENT,
    DE_RULE_FULL,
    OFFICER,
    ApiErrorId,
    accept_appointment,
    new_client,
    new_entity,
    new_home_registration,
    propose_appointment,
    publish_rule,
    read_appointment,
    read_entity,
    read_registration,
    setup_winding_down_entity,
    validate_error,
    validate_success,
)


def _proposed_but_unaccepted_agent():
    """A PENDING Delaware registration whose only appointment is still PROPOSED."""
    publish_rule(DE_RULE_FULL)
    client = new_client()
    entity = new_entity(client["id"])
    registration = new_home_registration(entity["id"])
    appointment = propose_appointment(registration)
    return {
        "client": client,
        "entity": entity,
        "registration": registration,
        "appointment": appointment,
    }


def test_activation_is_refused_while_the_agent_is_only_proposed(api):
    """PRD §2.9: "an agent appointment in status `APPOINTED` exists on the registration.
    Applies to `POST /registrations/{id}/activate`. Failure returns
    `ERR_AGENT_OF_RECORD_REQUIRED` (HTTP 409)."
    PRD §3.3: "The new appointment is created in status `PROPOSED` with
    `superseded_by_appointment_id` null, `resignation_noticed_on` null,
    `resignation_effective_on` null and `of_record` false, and the parent registration's
    `version` increases by 1."

    Design: Difficulty/cross_entity_state_dependency/registration_activation_requires_an_appointed_agent
    """
    scene = _proposed_but_unaccepted_agent()
    assert scene["appointment"]["status"] == "PROPOSED"

    response = api.activate_registration(scene["registration"]["id"], AGENT)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_AGENT_OF_RECORD_REQUIRED.value)
    assert read_registration(scene["registration"]["id"])["status"] == "PENDING"


def test_accepting_the_agent_unblocks_the_very_same_activation(api):
    """PRD §3.2: "On success the status becomes `ACTIVE`, `qualified_on` is stamped with
    the current clock date, the agent-of-record selection is re-run so that
    `agent_of_record_id` and every sibling appointment's `of_record` are refreshed,
    `delinquency_rank` is recomputed, the registration's `version` increases by 1, and
    the entity's `compliance_posture` and then the client's
    `portfolio_delinquency_status` are recomputed."
    PRD §3.3: "The first candidate under that ranking is the winner: the registration's
    `agent_of_record_id` is set to the winner's `id` and `of_record` is set true on the
    winner and false on every other appointment of that registration."

    Design: Difficulty/cross_entity_state_dependency/registration_activation_requires_an_appointed_agent
    """
    scene = _proposed_but_unaccepted_agent()
    api.activate_registration(scene["registration"]["id"], AGENT)

    accept_appointment(scene["appointment"]["id"])
    data = validate_success(
        api.activate_registration(scene["registration"]["id"], AGENT)
    )

    assert data["status"] == "ACTIVE"
    assert data["agent_of_record_id"] == scene["appointment"]["id"]
    # The logical clock has never been moved, so it still reads 2026-05-01.
    assert data["qualified_on"] == "2026-05-01"
    assert read_appointment(scene["appointment"]["id"])["of_record"] is True


def test_dissolution_is_refused_while_a_registration_is_still_occupied(api):
    """PRD §2.9: "every registration of the legal entity is in status `WITHDRAWN`,
    `TERMINATED` or `CLOSED_PERMANENT`; registered-agent service cannot end while any
    registration is still occupied. Applies to `POST /legal-entities/{id}/dissolve`.
    Failure returns `ERR_ACTIVE_REGISTRATIONS_EXIST` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/entity_dissolution_requires_every_registration_closed
    """
    scene = setup_winding_down_entity(DE_RULE_FULL)

    response = api.dissolve_legal_entity(scene["entity"]["id"], OFFICER)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_ACTIVE_REGISTRATIONS_EXIST.value)


def test_the_refused_dissolution_leaves_both_rows_exactly_as_they_were(api):
    """PRD §3.12: "On success `lifecycle_status` becomes `DISSOLVED`, the parallel
    `boi_status` axis is forced to `NOT_REQUIRED` from wherever it stood, the entity's
    `version` increases by 1, and the owning client's `portfolio_entity_count` is
    recomputed — the entity drops out of that count."
    PRD §3.12: "On success `lifecycle_status` becomes `WINDING_DOWN`,
    `final_report_required` is set true, and the entity's `version` increases by 1."

    Design: Difficulty/cross_entity_state_dependency/entity_dissolution_requires_every_registration_closed
    """
    scene = setup_winding_down_entity(DE_RULE_FULL)

    api.dissolve_legal_entity(scene["entity"]["id"], OFFICER)

    entity = read_entity(scene["entity"]["id"])
    assert entity["lifecycle_status"] == "WINDING_DOWN"
    assert entity["final_report_required"] is True
    assert read_registration(scene["registration"]["id"])["status"] == "ACTIVE"
