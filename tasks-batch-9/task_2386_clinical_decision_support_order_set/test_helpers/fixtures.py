"""Composite setup helpers that build precondition state through the API only.

Every test starts against an empty database, so any state a test needs must be
constructed here by calling published endpoints in the order the workflows
require. All helpers return plain dictionaries so a caller can pull whichever
identifiers, records or headers it needs.

Identity discipline: the six clinician-backed roles authenticate with the acting
clinician's own `id`, so these helpers always thread the created clinician's id
into its own headers. Only the administrative capabilities use the opaque
operator principal.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    build_activation_payload,
    build_adherence_measurement_payload,
    build_alert_payload,
    build_burden_window_payload,
    build_cast_payload,
    build_clinician_payload,
    build_clock_payload,
    build_close_window_payload,
    build_content_request_payload,
    build_disposition_payload,
    build_downtime_activation_payload,
    build_downtime_event_payload,
    build_firing_ingest_payload,
    build_impact_analysis_payload,
    build_order_set_item_payload,
    build_order_set_payload,
    build_pharmacy_signoff_payload,
    build_publish_payload,
    build_release_activation_payload,
    build_review_assignment_payload,
    build_submit_for_peer_review_payload,
    build_triage_payload,
    build_unit_observation,
    build_vendor_release_payload,
    build_vendor_rule_delta_payload,
)
from .test_users import (
    make_clinical_sponsor_headers,
    make_committee_chair_headers,
    make_informatics_builder_headers,
    make_peer_reviewer_headers,
    make_pharmacy_informaticist_headers,
    make_specialty_approver_headers,
    make_system_admin_headers,
)

ADMIN_HEADERS = make_system_admin_headers()


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock. Never performs a transition on its own."""
    return get_success_data(
        api_client.set_clock(build_clock_payload(to_iso8601), ADMIN_HEADERS)
    )


def reset_clock() -> Dict[str, Any]:
    """Return the logical clock to its starting instant."""
    return set_clock(CLOCK_START)


# --------------------------------------------------------------------------
# Clinician registration
# --------------------------------------------------------------------------


def register_clinician(authorized_roles: List[str], **overrides: Any) -> Dict[str, Any]:
    """Register one clinician with the given committee roles."""
    payload = build_clinician_payload(authorized_roles=authorized_roles, **overrides)
    return get_success_data(api_client.create_clinician(payload, ADMIN_HEADERS))


def create_sponsor(**overrides: Any) -> Dict[str, Any]:
    return register_clinician(
        ["ClinicalSponsor"],
        **{"full_name": "Sponsor Ruiz", "specialty": "CRITICAL_CARE", **overrides},
    )


def create_builder(**overrides: Any) -> Dict[str, Any]:
    return register_clinician(
        ["InformaticsBuilder"],
        **{"full_name": "Builder Nakamura", "specialty": "INFORMATICS", **overrides},
    )


def create_chair(**overrides: Any) -> Dict[str, Any]:
    return register_clinician(
        ["CommitteeChair"],
        **{"full_name": "Chair Adeyemi", "specialty": "HOSPITAL_MEDICINE", **overrides},
    )


def create_pharmacist(**overrides: Any) -> Dict[str, Any]:
    return register_clinician(
        ["PharmacyInformaticist"],
        **{"full_name": "Pharmacist Lindqvist", "specialty": "PHARMACY", **overrides},
    )


def create_peer_reviewer(label: str = "1", **overrides: Any) -> Dict[str, Any]:
    return register_clinician(
        ["PeerReviewer"],
        **{
            "full_name": f"Peer Reviewer {label}",
            "specialty": "INTERNAL_MEDICINE",
            **overrides,
        },
    )


def create_specialty_approver(label: str = "1", **overrides: Any) -> Dict[str, Any]:
    return register_clinician(
        ["SpecialtyApprover"],
        **{
            "full_name": f"Specialty Approver {label}",
            "specialty": "CARDIOLOGY",
            **overrides,
        },
    )


def setup_committee(
    peer_reviewer_count: int = 3, specialty_approver_count: int = 3
) -> Dict[str, Any]:
    """Register the standard committee cast and pre-build every header set.

    The reviewer pools are kept disjoint from the sponsor, the builder and the
    pharmacist so that no helper trips a segregation-of-duties or self-review
    constraint by accident.
    """
    sponsor = create_sponsor()
    builder = create_builder()
    chair = create_chair()
    pharmacist = create_pharmacist()
    peers = [create_peer_reviewer(str(index + 1)) for index in range(peer_reviewer_count)]
    specialists = [
        create_specialty_approver(str(index + 1)) for index in range(specialty_approver_count)
    ]

    committee: Dict[str, Any] = {
        "sponsor": sponsor,
        "builder": builder,
        "chair": chair,
        "pharmacist": pharmacist,
        "peers": peers,
        "specialists": specialists,
        "sponsor_headers": make_clinical_sponsor_headers(sponsor["id"]),
        "builder_headers": make_informatics_builder_headers(builder["id"]),
        "chair_headers": make_committee_chair_headers(chair["id"]),
        "pharmacist_headers": make_pharmacy_informaticist_headers(pharmacist["id"]),
        "peer_headers": [make_peer_reviewer_headers(peer["id"]) for peer in peers],
        "specialist_headers": [
            make_specialty_approver_headers(specialist["id"]) for specialist in specialists
        ],
        "admin_headers": ADMIN_HEADERS,
    }
    return committee


# --------------------------------------------------------------------------
# Vendor content releases
# --------------------------------------------------------------------------


def create_release(committee: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Record a vendor release in review_cycle_state RECEIVED."""
    payload = build_vendor_release_payload(**overrides)
    return get_success_data(
        api_client.create_vendor_release(payload, committee["pharmacist_headers"])
    )


def add_delta(
    committee: Dict[str, Any], release_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Record one rule delta against a received release."""
    payload = build_vendor_rule_delta_payload(**overrides)
    return get_success_data(
        api_client.create_vendor_rule_delta(
            release_id, payload, committee["pharmacist_headers"]
        )
    )


def run_impact_analysis(committee: Dict[str, Any], release_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.run_vendor_release_impact_analysis(
            release_id, build_impact_analysis_payload(), committee["pharmacist_headers"]
        )
    )


def disposition_all_deltas(
    committee: Dict[str, Any], release_id: str, disposition: str = "ACCEPT", **overrides: Any
) -> List[Dict[str, Any]]:
    """Disposition every delta of an analysed release."""
    deltas, _meta = _list_all(
        api_client.list_vendor_rule_deltas, release_id, committee["pharmacist_headers"]
    )
    results = []
    for delta in deltas:
        results.append(
            get_success_data(
                api_client.disposition_vendor_rule_delta(
                    delta["id"],
                    build_disposition_payload(disposition, **overrides),
                    committee["pharmacist_headers"],
                )
            )
        )
    return results


def setup_activated_release(
    committee: Dict[str, Any],
    release_overrides: Optional[Dict[str, Any]] = None,
    delta_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Drive a release through the fast-track branch to ACTIVATED.

    A single moderate new-interaction delta scores 3, which is below the
    clinical-review threshold, so the release forks onto the fast track and the
    pharmacist may activate it.
    """
    release = create_release(committee, **(release_overrides or {}))
    add_delta(committee, release["id"], **(delta_overrides or {}))
    run_impact_analysis(committee, release["id"])
    disposition_all_deltas(committee, release["id"])
    activated = get_success_data(
        api_client.activate_vendor_release(
            release["id"], build_release_activation_payload(), committee["pharmacist_headers"]
        )
    )
    return activated


# --------------------------------------------------------------------------
# Content requests
# --------------------------------------------------------------------------


def create_request(committee: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Submit a content request in status INTAKE_SUBMITTED."""
    payload = build_content_request_payload(committee["sponsor"]["id"], **overrides)
    return get_success_data(
        api_client.create_content_request(payload, committee["sponsor_headers"])
    )


def triage_request(
    committee: Dict[str, Any], request_id: str, decision: str = "ACCEPT", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.triage_content_request(
            request_id, build_triage_payload(decision, **overrides), committee["chair_headers"]
        )
    )


def setup_accepted_request(committee: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Submit and accept a content request, returning the accepted record."""
    request = create_request(committee, **overrides)
    return triage_request(committee, request["id"])


def read_request(committee: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_content_request(request_id, committee["chair_headers"])
    )


# --------------------------------------------------------------------------
# Order sets
# --------------------------------------------------------------------------


def build_order_set(
    committee: Dict[str, Any],
    content_request: Dict[str, Any],
    pinned_vendor_release_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a build against an accepted request, guarded by the request version."""
    payload = build_order_set_payload(
        committee["builder"]["id"],
        pinned_vendor_release_id,
        content_request["version"],
        **overrides,
    )
    return get_success_data(
        api_client.create_order_set(
            content_request["id"], payload, committee["builder_headers"]
        )
    )


def add_item(committee: Dict[str, Any], order_set_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = build_order_set_item_payload(**overrides)
    return get_success_data(
        api_client.create_order_set_item(order_set_id, payload, committee["builder_headers"])
    )


def sign_off(committee: Dict[str, Any], order_set_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record pharmacy sign-off by the committee's pharmacist."""
    payload = build_pharmacy_signoff_payload(committee["pharmacist"]["id"], **overrides)
    return get_success_data(
        api_client.record_pharmacy_signoff(
            order_set_id, payload, committee["pharmacist_headers"]
        )
    )


def submit_for_peer_review(
    committee: Dict[str, Any], order_set_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_order_set_for_peer_review(
            order_set_id,
            build_submit_for_peer_review_payload(**overrides),
            committee["builder_headers"],
        )
    )


def read_order_set(committee: Dict[str, Any], order_set_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_order_set(order_set_id, committee["chair_headers"]))


def setup_draft_order_set(
    committee: Dict[str, Any],
    request_overrides: Optional[Dict[str, Any]] = None,
    order_set_overrides: Optional[Dict[str, Any]] = None,
    item_payloads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Activated release, accepted request, one build in DRAFT with items.

    Returns a scenario dict with keys release, content_request, order_set and
    items. When `item_payloads` is omitted a single lab line is added so the
    build already satisfies the at-least-one-item submission requirement.
    """
    release = setup_activated_release(committee)
    content_request = setup_accepted_request(committee, **(request_overrides or {}))
    order_set = build_order_set(
        committee, content_request, release["id"], **(order_set_overrides or {})
    )
    payloads = item_payloads if item_payloads is not None else [{}]
    items = [add_item(committee, order_set["id"], **payload) for payload in payloads]
    return {
        "release": release,
        "content_request": read_request(committee, content_request["id"]),
        "order_set": read_order_set(committee, order_set["id"]),
        "items": items,
    }


def assign_reviewer(
    committee: Dict[str, Any],
    reviewer_id: str,
    review_kind: str,
    order_set_id: Optional[str] = None,
    alert_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_review_assignment_payload(
        reviewer_id, review_kind, order_set_id=order_set_id, alert_id=alert_id, **overrides
    )
    return get_success_data(
        api_client.create_review_assignment(payload, committee["chair_headers"])
    )


def cast_vote(
    committee: Dict[str, Any],
    assignment_id: str,
    reviewer_headers: Dict[str, str],
    vote: str = "APPROVE",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.cast_review_vote(
            assignment_id, build_cast_payload(vote, **overrides), reviewer_headers
        )
    )


def _required_votes_for(risk_class: str) -> int:
    """The base vote requirement: 3 for HIGH, 2 for STANDARD."""
    return 3 if risk_class == "HIGH" else 2


def run_peer_stage(committee: Dict[str, Any], order_set_id: str) -> List[Dict[str, Any]]:
    """Assign and approve enough peer reviewers to clear the peer quorum."""
    order_set = read_order_set(committee, order_set_id)
    needed = _required_votes_for(order_set["risk_class"])
    assignments = []
    for index in range(needed):
        assignment = assign_reviewer(
            committee,
            committee["peers"][index]["id"],
            "PEER_REVIEW",
            order_set_id=order_set_id,
        )
        assignments.append(assignment)
    for index, assignment in enumerate(assignments):
        cast_vote(committee, assignment["id"], committee["peer_headers"][index], "APPROVE")
    return assignments


def run_specialty_stage(committee: Dict[str, Any], order_set_id: str) -> List[Dict[str, Any]]:
    """Assign and approve enough specialty approvers to clear the specialty quorum."""
    order_set = read_order_set(committee, order_set_id)
    needed = _required_votes_for(order_set["risk_class"])
    assignments = []
    for index in range(needed):
        assignment = assign_reviewer(
            committee,
            committee["specialists"][index]["id"],
            "SPECIALTY_APPROVAL",
            order_set_id=order_set_id,
        )
        assignments.append(assignment)
    for index, assignment in enumerate(assignments):
        cast_vote(
            committee, assignment["id"], committee["specialist_headers"][index], "APPROVE"
        )
    return assignments


def setup_order_set_in_peer_review(
    committee: Dict[str, Any], **kwargs: Any
) -> Dict[str, Any]:
    """A build submitted into PEER_REVIEW."""
    scenario = setup_draft_order_set(committee, **kwargs)
    submit_for_peer_review(committee, scenario["order_set"]["id"])
    scenario["order_set"] = read_order_set(committee, scenario["order_set"]["id"])
    return scenario


def setup_order_set_in_specialty_approval(
    committee: Dict[str, Any], **kwargs: Any
) -> Dict[str, Any]:
    """A build whose peer stage has reached quorum."""
    scenario = setup_order_set_in_peer_review(committee, **kwargs)
    scenario["peer_assignments"] = run_peer_stage(committee, scenario["order_set"]["id"])
    scenario["order_set"] = read_order_set(committee, scenario["order_set"]["id"])
    return scenario


def setup_approved_order_set(committee: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """A build in review_state APPROVED and publication_state UNPUBLISHED."""
    scenario = setup_order_set_in_specialty_approval(committee, **kwargs)
    scenario["specialty_assignments"] = run_specialty_stage(
        committee, scenario["order_set"]["id"]
    )
    scenario["deciding_specialty_assignment"] = scenario["specialty_assignments"][-1]
    scenario["order_set"] = read_order_set(committee, scenario["order_set"]["id"])
    return scenario


def publish(
    committee: Dict[str, Any],
    order_set_id: str,
    go_live_at: str = CLOCK_START,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.publish_order_set(
            order_set_id,
            build_publish_payload(go_live_at, **overrides),
            committee["chair_headers"],
        )
    )


def setup_published_order_set(
    committee: Dict[str, Any], go_live_at: str = CLOCK_START, **kwargs: Any
) -> Dict[str, Any]:
    """A build carried all the way to publication_state PUBLISHED."""
    scenario = setup_approved_order_set(committee, **kwargs)
    scenario["order_set"] = publish(committee, scenario["order_set"]["id"], go_live_at)
    scenario["go_live_at"] = go_live_at
    return scenario


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------


def design_alert(
    committee: Dict[str, Any],
    content_request: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_alert_payload(committee["builder"]["id"], **overrides)
    return get_success_data(
        api_client.create_alert(content_request["id"], payload, committee["builder_headers"])
    )


def read_alert(committee: Dict[str, Any], alert_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_alert(alert_id, committee["chair_headers"]))


def _alert_required_votes(severity_tier: str) -> int:
    return {"TIER_1_HARD_STOP": 3, "TIER_2_INTERRUPTIVE": 2, "TIER_3_PASSIVE": 1}[
        severity_tier
    ]


def run_alert_approval_stage(
    committee: Dict[str, Any], alert_id: str
) -> List[Dict[str, Any]]:
    """Assign and unanimously approve enough reviewers to clear the alert quorum."""
    alert = read_alert(committee, alert_id)
    needed = _alert_required_votes(alert["severity_tier"])
    assignments = []
    for index in range(needed):
        assignments.append(
            assign_reviewer(
                committee,
                committee["specialists"][index]["id"],
                "SPECIALTY_APPROVAL",
                alert_id=alert_id,
            )
        )
    for index, assignment in enumerate(assignments):
        cast_vote(
            committee, assignment["id"], committee["specialist_headers"][index], "APPROVE"
        )
    return assignments


def setup_draft_alert(
    committee: Dict[str, Any],
    request_overrides: Optional[Dict[str, Any]] = None,
    alert_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An accepted request plus one alert in DRAFT / UNPUBLISHED."""
    content_request = setup_accepted_request(
        committee, **{"request_type": "ALERT", **(request_overrides or {})}
    )
    alert = design_alert(committee, content_request, **(alert_overrides or {}))
    return {
        "content_request": read_request(committee, content_request["id"]),
        "alert": read_alert(committee, alert["id"]),
    }


def setup_approved_alert(committee: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """An alert in review_state APPROVED and lifecycle_state UNPUBLISHED."""
    scenario = setup_draft_alert(committee, **kwargs)
    scenario["approval_assignments"] = run_alert_approval_stage(
        committee, scenario["alert"]["id"]
    )
    scenario["deciding_approval_assignment"] = scenario["approval_assignments"][-1]
    scenario["alert"] = read_alert(committee, scenario["alert"]["id"])
    return scenario


def activate_alert(
    committee: Dict[str, Any], alert_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.activate_alert(
            alert_id, build_activation_payload(**overrides), committee["chair_headers"]
        )
    )


def setup_active_alert(committee: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """An alert carried to lifecycle_state ACTIVE."""
    scenario = setup_approved_alert(committee, **kwargs)
    scenario["alert"] = activate_alert(committee, scenario["alert"]["id"])
    return scenario


def setup_published_order_set_with_linked_alert(
    committee: Dict[str, Any],
    go_live_at: str = CLOCK_START,
    alert_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """One request producing both a published order set and an alert linked to it.

    The request carries `request_type` BOTH so that closure requires both a
    published order set and an active alert.
    """
    request_overrides = dict(kwargs.pop("request_overrides", None) or {})
    request_overrides.setdefault("request_type", "BOTH")
    scenario = setup_published_order_set(
        committee, go_live_at, request_overrides=request_overrides, **kwargs
    )
    content_request = read_request(committee, scenario["content_request"]["id"])
    alert = design_alert(
        committee,
        content_request,
        **{
            "linked_order_set_id": scenario["order_set"]["id"],
            **(alert_overrides or {}),
        },
    )
    scenario["alert"] = read_alert(committee, alert["id"])
    scenario["content_request"] = read_request(committee, content_request["id"])
    return scenario


# --------------------------------------------------------------------------
# Firing ingest and burden windows
# --------------------------------------------------------------------------


def ingest_firings(
    alert_id: str,
    fired_at_start: str,
    fire_count: int,
    override_count: int,
    distinct_clinician_count: int,
    interval_seconds: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    """Deterministically create one batch of firing records."""
    payload = build_firing_ingest_payload(
        alert_id,
        fired_at_start,
        fire_count,
        override_count,
        distinct_clinician_count,
        interval_seconds,
        **overrides,
    )
    return get_success_data(api_client.ingest_alert_firings(payload, ADMIN_HEADERS))


def open_window(
    committee: Dict[str, Any],
    alert_id: str,
    window_start: str,
    window_end: str,
    expected_alert_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a burden window, reading the alert version when none is supplied."""
    if expected_alert_version is None:
        expected_alert_version = read_alert(committee, alert_id)["version"]
    payload = build_burden_window_payload(
        window_start, window_end, expected_alert_version, **overrides
    )
    return get_success_data(
        api_client.create_burden_window(alert_id, payload, committee["chair_headers"])
    )


def close_window(
    committee: Dict[str, Any], alert_id: str, window_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_burden_window(
            alert_id, window_id, build_close_window_payload(**overrides), committee["chair_headers"]
        )
    )


def read_windows(committee: Dict[str, Any], alert_id: str) -> List[Dict[str, Any]]:
    windows, _meta = _list_all(
        api_client.list_burden_windows, alert_id, committee["chair_headers"]
    )
    return windows


def setup_alert_with_closed_window(
    committee: Dict[str, Any],
    window_start: str,
    window_end: str,
    fire_count: int,
    override_count: int,
    distinct_clinician_count: int,
    interval_seconds: int = 60,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An active alert with one window of ingested firings, then closed."""
    scenario = setup_active_alert(committee, **kwargs)
    alert_id = scenario["alert"]["id"]
    scenario["ingest"] = ingest_firings(
        alert_id,
        window_start,
        fire_count,
        override_count,
        distinct_clinician_count,
        interval_seconds,
    )
    window = open_window(committee, alert_id, window_start, window_end)
    scenario["window"] = close_window(committee, alert_id, window["id"])
    scenario["alert"] = read_alert(committee, alert_id)
    return scenario


# --------------------------------------------------------------------------
# Downtime events
# --------------------------------------------------------------------------


def schedule_downtime(
    window_start: str, window_end: str, scope: str = "SYSTEM_WIDE", mode: str = "READ_ONLY", **overrides: Any
) -> Dict[str, Any]:
    payload = build_downtime_event_payload(
        window_start, window_end, scope, mode, **overrides
    )
    return get_success_data(api_client.create_downtime_event(payload, ADMIN_HEADERS))


def activate_downtime(downtime_event_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.activate_downtime_event(
            downtime_event_id, build_downtime_activation_payload(**overrides), ADMIN_HEADERS
        )
    )


def setup_active_downtime(
    window_start: str,
    window_end: str,
    scope: str = "SYSTEM_WIDE",
    mode: str = "READ_ONLY",
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule and activate a downtime event so the freeze is in force.

    The caller is responsible for having the logical clock inside the supplied
    window, because activation requires it.
    """
    event = schedule_downtime(window_start, window_end, scope, mode, **overrides)
    return activate_downtime(event["id"])


def read_downtime(downtime_event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_downtime_event(downtime_event_id, ADMIN_HEADERS))


# --------------------------------------------------------------------------
# Adherence measurement
# --------------------------------------------------------------------------


def create_measurement(
    committee: Dict[str, Any],
    order_set_id: str,
    measurement_period_start: str,
    measurement_period_end: str,
    unit_observations: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_adherence_measurement_payload(
        measurement_period_start, measurement_period_end, unit_observations, **overrides
    )
    return get_success_data(
        api_client.create_adherence_measurement(
            order_set_id, payload, committee["chair_headers"]
        )
    )


def setup_provisional_measurement(
    committee: Dict[str, Any],
    measurement_period_start: str,
    measurement_period_end: str,
    unit_observations: Optional[List[Dict[str, Any]]] = None,
    go_live_at: str = CLOCK_START,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A published order set plus one observation set in PROVISIONAL."""
    scenario = setup_published_order_set(committee, go_live_at, **kwargs)
    scenario["measurement"] = create_measurement(
        committee,
        scenario["order_set"]["id"],
        measurement_period_start,
        measurement_period_end,
        unit_observations if unit_observations is not None else [build_unit_observation()],
    )
    return scenario


# --------------------------------------------------------------------------
# Annual review tasks and the sweep
# --------------------------------------------------------------------------


def read_tasks(committee: Dict[str, Any], **filters: Any) -> List[Dict[str, Any]]:
    params = {"limit": 100, **filters}
    response = api_client.list_annual_review_tasks(committee["chair_headers"], params)
    return get_success_data(response)


def task_for_order_set(committee: Dict[str, Any], order_set_id: str) -> Dict[str, Any]:
    tasks = read_tasks(committee, order_set_id=order_set_id)
    assert tasks, f"no annual review task governs order set {order_set_id}"
    return tasks[0]


def task_for_alert(committee: Dict[str, Any], alert_id: str) -> Dict[str, Any]:
    tasks = read_tasks(committee, alert_id=alert_id)
    assert tasks, f"no annual review task governs alert {alert_id}"
    return tasks[0]


def run_sweep(committee: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    payload = dict(overrides)
    return get_success_data(api_client.run_expiration_sweep(payload, committee["chair_headers"]))


# --------------------------------------------------------------------------
# Internal
# --------------------------------------------------------------------------


def _list_all(list_method, resource_id: str, headers: Dict[str, str]):
    """Read a nested list endpoint with the maximum page size."""
    response = list_method(resource_id, headers, {"limit": 100})
    body = response.json()
    return body["data"], body["meta"]
