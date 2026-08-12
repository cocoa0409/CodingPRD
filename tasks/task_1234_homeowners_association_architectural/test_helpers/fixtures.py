"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.
Owner-backed roles always thread the acting Owner's real id through
make_*_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_association_payload, create_owner_payload, create_property_payload,
    create_blackout_payload, create_variance_payload, create_application_payload,
    create_attachment_payload, create_vote_payload, create_decision_payload,
    create_appeal_payload, create_violation_payload, create_clock_payload,
)
from .test_users import (
    TEST_USERS, make_homeowner_headers, make_committee_member_headers,
)
from .constants import TEST_DEFAULTS

MANAGER = TEST_USERS["manager_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
EPOCH = TEST_DEFAULTS["EPOCH"]


def _ok(res, what):
    assert res.status_code < 400, f"Setup failed: {what} -> {res.status_code} {res.text}"
    return get_success_data(res)


# --- Single-resource creators -------------------------------------------------

def create_association(**overrides) -> dict:
    return _ok(api_client.create_association(
        create_association_payload(**overrides), MANAGER), "create_association")


def register_owner(association_id: str, full_name: str = "Ann A",
                   email: str = "ann.a@example.com") -> dict:
    return _ok(api_client.create_owner(
        association_id, create_owner_payload(full_name=full_name, email=email),
        MANAGER), "register_owner")


def register_committee(association_id: str, count: int = 3, prefix: str = "Cm") -> list:
    """Register `count` distinct committee-eligible owners (none is an applicant)."""
    owners = []
    for i in range(count):
        owners.append(register_owner(
            association_id, full_name=f"{prefix} {i + 1}",
            email=f"{prefix.lower()}{i + 1}@example.com"))
    return owners


def register_property(association_id: str, primary_owner_id: str,
                      lot_number: str = "L-1", address: str = "1 Main St") -> dict:
    return _ok(api_client.create_property(
        association_id,
        create_property_payload(primary_owner_id, lot_number=lot_number, address=address),
        MANAGER), "register_property")


def set_logical_clock(to_iso8601: str = EPOCH) -> dict:
    return _ok(api_client.set_clock(create_clock_payload(to_iso8601), MANAGER), "set_clock")


def run_daily_sweep() -> dict:
    return _ok(api_client.run_daily_sweep(MANAGER), "run_daily_sweep")


# --- Application pipeline (Tier 1 + 2) -----------------------------------------

def create_draft_application(property_id: str, owner: dict, **overrides) -> dict:
    """Create a DRAFT application owned by `owner` (identity threaded)."""
    return _ok(api_client.create_application(
        property_id, create_application_payload(owner["id"], **overrides),
        make_homeowner_headers(owner["id"])), "create_application")


def add_required_attachments(application_id: str, owner_id: str):
    """Attach one DRAWING and one MATERIAL_SAMPLE (submission completeness)."""
    headers = make_homeowner_headers(owner_id)
    _ok(api_client.create_attachment(
        application_id, create_attachment_payload("DRAWING"), headers), "attach drawing")
    _ok(api_client.create_attachment(
        application_id, create_attachment_payload("MATERIAL_SAMPLE"), headers),
        "attach material sample")


def create_complete_draft(property_id: str, owner: dict, **overrides) -> dict:
    app = create_draft_application(property_id, owner, **overrides)
    add_required_attachments(app["id"], owner["id"])
    return app


def submit_application(application_id: str, owner_id: str) -> dict:
    return _ok(api_client.submit_application(
        application_id, make_homeowner_headers(owner_id)), "submit_application")


def start_review(application_id: str) -> dict:
    return _ok(api_client.start_review(application_id, MANAGER), "start_review")


def cast_ballots(application_id: str, committee: list, ballots) -> list:
    """Cast one ballot per (committee member, ballot) pair; identity threaded."""
    votes = []
    for member, ballot in zip(committee, ballots):
        votes.append(_ok(api_client.cast_vote(
            application_id, create_vote_payload(ballot),
            make_committee_member_headers(member["id"])), "cast_vote"))
    return votes


def create_under_review_application(property_id: str, owner: dict, committee: list,
                                    ballots=("APPROVE", "APPROVE", "APPROVE"),
                                    **app_overrides) -> dict:
    """Complete DRAFT -> SUBMITTED -> UNDER_REVIEW, with ballots cast."""
    app = create_complete_draft(property_id, owner, **app_overrides)
    submit_application(app["id"], owner["id"])
    started = start_review(app["id"])
    if ballots:
        cast_ballots(app["id"], committee, ballots)
    return started


def decide(application_id: str, conditions=None, denial_reason=None) -> dict:
    return _ok(api_client.decide_application(
        application_id, create_decision_payload(conditions, denial_reason),
        MANAGER), "decide_application")


def get_single_permit(application_id: str) -> dict:
    """PRD §3.7: at most one permit ever exists per application."""
    data = _ok(api_client.list_application_permits(application_id, MANAGER),
               "list_application_permits")
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly 1 permit for application {application_id}, "
        f"got {data}")
    return data[0]


def get_violation_fine(violation_id: str) -> dict:
    """PRD §3.8: exactly one fine per violation, listable as a one-entry collection."""
    data = _ok(api_client.list_violation_fines(violation_id, MANAGER),
               "list_violation_fines")
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly 1 fine for violation {violation_id}, got {data}")
    return data[0]


def get_inspection_violation(inspection_id: str) -> dict:
    """PRD §3.7: violations of a failed inspection listable as a zero-or-one collection."""
    data = _ok(api_client.list_inspection_violations(inspection_id, MANAGER),
               "list_inspection_violations")
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly 1 violation for inspection {inspection_id}, "
        f"got {data}")
    return data[0]


def read_property(property_id: str) -> dict:
    return _ok(api_client.get_property(property_id, MANAGER), "get_property")


def read_application(application_id: str) -> dict:
    return _ok(api_client.get_application(application_id, MANAGER), "get_application")


# --- Tier 2/3 composite scenarios ----------------------------------------------

def setup_review_ready(ballots=("APPROVE", "APPROVE", "APPROVE"), num_committee=3,
                       assoc_overrides=None, app_overrides=None,
                       property_id=None, applicant=None, clock=EPOCH) -> dict:
    """Association + applicant + committee owners + property + complete
    application in UNDER_REVIEW with `ballots` cast.

    Returns {"association", "applicant", "committee", "property", "application"}.
    """
    assoc = create_association(**(assoc_overrides or {}))
    owner = applicant or register_owner(assoc["id"], full_name="Ann A",
                                        email="ann.a@example.com")
    committee = register_committee(
        assoc["id"], count=max(num_committee, len(ballots or ())))
    prop = {"id": property_id} if property_id else register_property(
        assoc["id"], owner["id"])
    set_logical_clock(clock)
    app = create_under_review_application(
        prop["id"], owner, committee, ballots=ballots, **(app_overrides or {}))
    return {"association": assoc, "applicant": owner, "committee": committee,
            "property": prop, "application": app}


def setup_approved_with_permit(assoc_overrides=None, app_overrides=None,
                               conditions=None, clock=EPOCH) -> dict:
    """Full pipeline through committee approval; returns bundle incl. permit."""
    bundle = setup_review_ready(assoc_overrides=assoc_overrides,
                                app_overrides=app_overrides, clock=clock)
    decided = decide(bundle["application"]["id"],
                     conditions=conditions if conditions is not None else [])
    bundle["application"] = decided
    bundle["permit"] = get_single_permit(bundle["application"]["id"])
    return bundle


def setup_denied_application(ballots=("APPROVE", "DENY", "DENY"),
                             denial_reason="exceeds fence height cap",
                             assoc_overrides=None, app_overrides=None,
                             clock=EPOCH) -> dict:
    """Application decided DENIED under the supermajority tally."""
    bundle = setup_review_ready(ballots=ballots, assoc_overrides=assoc_overrides,
                                app_overrides=app_overrides, clock=clock)
    bundle["application"] = decide(bundle["application"]["id"],
                                   denial_reason=denial_reason)
    assert bundle["application"]["status"] == "DENIED", (
        f"Setup failed: expected DENIED, got {bundle['application']['status']}")
    return bundle


def setup_violation_with_fine(assoc_overrides=None, kind="UNAPPROVED_WORK",
                              description="unapproved shed", clock=EPOCH) -> dict:
    """Association + owner + property + manager-reported violation + its fine.

    Returns {"association", "owner", "property", "violation", "fine"}.
    """
    assoc = create_association(**(assoc_overrides or {}))
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"])
    set_logical_clock(clock)
    violation = _ok(api_client.create_violation(
        prop["id"], create_violation_payload(kind, description=description),
        MANAGER), "create_violation")
    fine = get_violation_fine(violation["id"])
    return {"association": assoc, "owner": owner, "property": prop,
            "violation": violation, "fine": fine}


def setup_liened_property(assoc_overrides=None, clock=EPOCH,
                          sweep_date="2026-05-02T09:00:00Z") -> dict:
    """Property driven to LIENED: violation whose base fine reaches the lien
    threshold, then a next-day sweep auto-files the lien (PRD §3.8).

    Returns the violation bundle plus "lien" and post-sweep "sweep_report".
    """
    overrides = {"lien_threshold_cents": TEST_DEFAULTS["BASE_FINE_CENTS"],
                 "lien_min_age_days": 0}
    overrides.update(assoc_overrides or {})
    bundle = setup_violation_with_fine(assoc_overrides=overrides, clock=clock)
    set_logical_clock(sweep_date)
    report = run_daily_sweep()
    assert report["liens_filed"] == 1, (
        f"Setup failed: expected 1 lien filed, got {report['liens_filed']}")
    liens = _ok(api_client.list_liens(bundle["property"]["id"], MANAGER),
                "list_liens")
    assert len(liens) == 1, f"Setup failed: expected 1 lien, got {liens}"
    bundle["lien"] = liens[0]
    bundle["sweep_report"] = report
    bundle["property"] = read_property(bundle["property"]["id"])
    assert bundle["property"]["compliance_posture"] == "LIENED", (
        f"Setup failed: posture {bundle['property']['compliance_posture']}")
    return bundle


def setup_failed_inspection(assoc_overrides=None, app_overrides=None,
                            result_notes="setback short by 2ft") -> dict:
    """Approved permit -> inspection SCHEDULED -> recorded FAIL.

    Returns the approval bundle plus "inspection", "violation", "fine",
    with the logical clock at 2026-06-10 (inside the default window).
    """
    bundle = setup_approved_with_permit(assoc_overrides=assoc_overrides,
                                        app_overrides=app_overrides)
    set_logical_clock("2026-06-10T09:00:00Z")
    inspection = _ok(api_client.request_inspection(
        bundle["permit"]["id"],
        make_homeowner_headers(bundle["applicant"]["id"])), "request_inspection")
    recorded = _ok(api_client.record_inspection(
        inspection["id"],
        {"result": "FAIL", "result_notes": result_notes},
        INSPECTOR), "record_inspection FAIL")
    assert recorded["status"] == "FAILED_REMEDIATION", (
        f"Setup failed: inspection status {recorded['status']}")
    violation = get_inspection_violation(inspection["id"])
    bundle["inspection"] = recorded
    bundle["violation"] = violation
    bundle["fine"] = get_violation_fine(violation["id"])
    return bundle
