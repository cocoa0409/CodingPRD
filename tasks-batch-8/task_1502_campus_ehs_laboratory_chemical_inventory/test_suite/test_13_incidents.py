"""Incident reporting/closure and the posture reconciliation around HIGH incidents."""
from test_helpers import (
    TEST_USERS,
    create_incident,
    create_lab_with_pi,
    get_lab,
    make_pi_headers,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_incident_report_and_close_valid(api):
    """PRD §3.6: "The incident opens in `REPORTED` status, the reporter's `X-User-ID`
    is recorded as `reported_by`"
    PRD §3.6: "Closure is an `EHSAdmin` action that moves the incident from
    `REPORTED` to its terminal `CLOSED` status, storing the supplied `resolution`
    narrative."

    Design: Corner/state_machines/incident_report_and_close_valid
    """
    lab, pi = create_lab_with_pi(name="Lab J", room="107")
    incident = create_incident(
        lab["id"], make_pi_headers(pi["id"]),
        title="Spill", description="100ml ethanol spill", severity="LOW", near_miss=False,
    )
    assert incident["status"] == "REPORTED"
    assert incident["reported_by"] == pi["id"], (
        "reported_by records the reporter's X-User-ID"
    )

    closed = validate_success(
        api.close_incident(incident["id"], {"resolution": "cleaned per SOP"}, ADMIN), 200
    )
    assert closed["status"] == "CLOSED"
    assert closed["resolution"] == "cleaned per SOP"


def test_open_high_incident_restricts_then_close_restores(api):
    """PRD §2.6: "Otherwise, if exactly one incident of the lab is in `REPORTED`
    status with `severity` equal to `HIGH`, posture is `RESTRICTED`."
    PRD §3.6: "Because closure shrinks the open-incident population, the lab's
    posture is recomputed and the incident's `version` increments by 1."
    PRD §3.6: "Anyone on the ground — `LabMember`, `PrincipalInvestigator`, or
    `EHSAdmin` — reports an incident for a lab by supplying the `lab_id`, a short
    `title`, a `description` of what happened (spill, exposure, near-miss), a
    `severity` of `LOW`, `MEDIUM`, or `HIGH`, and optionally the `near_miss` flag,
    which defaults to false"

    Design: Corner/complexity_layers/open_high_incident_restricts_then_close_restores
    """
    lab, pi = create_lab_with_pi(name="Lab DF", room="126")
    assert get_lab(lab["id"])["posture"] == "NORMAL"

    incident = create_incident(
        lab["id"], make_pi_headers(pi["id"]),
        title="Acid splash", description="minor splash, no injury",
        severity="HIGH", near_miss=True,
    )
    assert incident["near_miss"] is True
    assert get_lab(lab["id"])["posture"] == "RESTRICTED", (
        "one open HIGH incident degrades posture to RESTRICTED"
    )

    closed = validate_success(
        api.close_incident(
            incident["id"], {"resolution": "reviewed, PPE retrained"}, ADMIN
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["version"] == incident["version"] + 1
    assert get_lab(lab["id"])["posture"] == "NORMAL", (
        "closing the incident recomputes posture back to NORMAL"
    )
