"""Composite setup helpers.

Every test runs against an empty database, so each helper here builds its
preconditions from scratch using only the endpoints the PRD declares. Helpers
use the lenient success validator so a broken precondition surfaces as a clear
setup failure rather than as a confusing assertion.

Ordering note: locations are ingested while the program is still ``DRAFT``,
because opening the challenge window requires ``location_count_total`` to be at
least 1.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_application_payload,
    create_award_payload,
    create_challenge_payload,
    create_compliance_audit_payload,
    create_environmental_determination_payload,
    create_environmental_review_payload,
    create_evidence_payload,
    create_location_claim_payload,
    create_location_payload,
    create_milestone_payload,
    create_program_payload,
    create_score_sheet_payload,
    create_subgrantee_payload,
    record_audit_result_payload,
    submit_milestone_evidence_payload,
    verify_milestone_payload,
)
from .test_users import (
    ADMIN_1,
    ANALYST_1,
    AUDITOR_1,
    AUDITOR_2,
    COMMUNITY_1,
    EHP_1,
    PROVIDER_2,
    REVIEWER_1,
    SCORER_1,
    TEST_USERS,
    make_subgrantee_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANALYST = TEST_USERS["eligibility_analyst_headers"]
ANALYST_OTHER = TEST_USERS["eligibility_analyst_2_headers"]
REVIEWER = TEST_USERS["capability_reviewer_headers"]
SCORER = TEST_USERS["scoring_officer_headers"]
EHP = TEST_USERS["environmental_reviewer_headers"]
AUDITOR = TEST_USERS["audit_officer_headers"]
AUDITOR_OTHER = TEST_USERS["audit_officer_2_headers"]
CHALLENGER = TEST_USERS["challenger_headers"]
PROVIDER = TEST_USERS["provider_headers"]


# The canonical national-map readings used across the suite. Under the default
# thresholds L1 classifies SERVED, L2 and L5 UNDERSERVED and L3 UNSERVED.
CANONICAL_LOCATIONS = {
    "L1": {
        "address_id": "ADDR-0001",
        "reported_down_mbps": 200,
        "reported_up_mbps": 25,
        "reported_latency_ms": 30,
        "reported_technology": "FIBER",
    },
    "L2": {
        "address_id": "ADDR-0002",
        "reported_down_mbps": 50,
        "reported_up_mbps": 10,
        "reported_latency_ms": 40,
        "reported_technology": "CABLE",
    },
    "L3": {
        "address_id": "ADDR-0003",
        "reported_down_mbps": 10,
        "reported_up_mbps": 1,
        "reported_latency_ms": 50,
        "reported_technology": "DSL",
    },
    "L5": {
        "address_id": "ADDR-0005",
        "reported_down_mbps": 25,
        "reported_up_mbps": 3,
        "reported_latency_ms": 60,
        "reported_technology": "DSL",
    },
}


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def set_clock(current_utc):
    """Move the logical clock. The clock setter requires no acting user."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def create_program(**overrides):
    """Create a grant program round in DRAFT."""
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN)
    )


def ingest_location(program_id, address_id, **overrides):
    """Ingest one national-map location and classify it."""
    return get_success_data(
        api_client.create_location(
            create_location_payload(program_id, address_id, **overrides), ANALYST
        )
    )


def ingest_canonical_location(program_id, key, **overrides):
    """Ingest one of the canonical readings by key."""
    spec = dict(CANONICAL_LOCATIONS[key])
    address_id = spec.pop("address_id")
    spec.update(overrides)
    return ingest_location(program_id, address_id, **spec)


def open_challenge_window(program_id):
    return get_success_data(api_client.open_challenge_window(program_id, ADMIN))


def close_challenge_window(program_id):
    return get_success_data(api_client.close_challenge_window(program_id, ADMIN))


def open_scoring(program_id):
    return get_success_data(api_client.open_scoring(program_id, ADMIN))


def close_allocation(program_id):
    return get_success_data(api_client.close_allocation(program_id, ADMIN))


def read_program(program_id):
    return get_success_data(api_client.get_program(program_id, ADMIN))


def read_location(location_id):
    return get_success_data(api_client.get_location(location_id, ADMIN))


def read_challenge(challenge_id):
    return get_success_data(api_client.get_challenge(challenge_id, ADMIN))


def read_subgrantee(subgrantee_id):
    return get_success_data(api_client.get_subgrantee(subgrantee_id, ADMIN))


def read_application(application_id):
    return get_success_data(api_client.get_application(application_id, ADMIN))


def read_award(award_id):
    return get_success_data(api_client.get_award(award_id, ADMIN))


def current_application_version(application_id):
    """Read the application's live version, as a scoring client would."""
    return get_success_data(api_client.get_application(application_id, SCORER))[
        "version"
    ]


def current_challenge_version(challenge_id, headers=None):
    """Read the challenge's live version, as an appending client would."""
    return get_success_data(
        api_client.get_challenge(challenge_id, headers or CHALLENGER)
    )["version"]


# --------------------------------------------------------------------------
# Tier 1: program standing up with its location inventory
# --------------------------------------------------------------------------


def setup_draft_program_with_locations(location_keys=("L1", "L2", "L3"), **program_overrides):
    """Program in DRAFT plus its ingested locations, clock untouched.

    Returns a context dict with ``program``, ``program_id``, ``locations``
    (keyed by canonical key) and ``location_ids``.
    """
    program = create_program(**program_overrides)
    locations = {}
    for key in location_keys:
        locations[key] = ingest_canonical_location(program["id"], key)
    return {
        "program": program,
        "program_id": program["id"],
        "locations": locations,
        "location_ids": {k: v["id"] for k, v in locations.items()},
    }


def setup_challenge_open_program(
    location_keys=("L1", "L2", "L3"),
    clock=TEST_DEFAULTS["OPEN_CLOCK"],
    **program_overrides,
):
    """Program advanced to CHALLENGE_OPEN with the logical clock inside the
    challenge window and its location inventory ingested."""
    ctx = setup_draft_program_with_locations(location_keys, **program_overrides)
    set_clock(clock)
    ctx["program"] = open_challenge_window(ctx["program_id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 2: challenges and their evidentiary record
# --------------------------------------------------------------------------


def file_challenge(program_id, location_id, headers=None, **overrides):
    """File a challenge contesting a location's classification."""
    return get_success_data(
        api_client.create_challenge(
            create_challenge_payload(program_id, location_id, **overrides),
            headers or CHALLENGER,
        )
    )


def append_evidence(
    challenge_id,
    evidence_type,
    collected_at,
    headers=None,
    expected_challenge_version=None,
    **overrides,
):
    """Append one evidence item, refreshing the parent version first.

    Every append recomputes the challenge's evidence scores and therefore
    increments the challenge's version, so the guard value is re-read unless the
    caller pins one deliberately.
    """
    caller = headers or CHALLENGER
    version = (
        expected_challenge_version
        if expected_challenge_version is not None
        else current_challenge_version(challenge_id, caller)
    )
    return get_success_data(
        api_client.append_challenge_evidence(
            challenge_id,
            create_evidence_payload(evidence_type, collected_at, version, **overrides),
            caller,
        )
    )


def setup_community_challenge_meeting_standard(
    program_id,
    location_id,
    submitter_headers=None,
    challenger_type="COMMUNITY",
    rationale="Community filing with two evidence types.",
):
    """A challenge carrying a SERVICE_DENIAL_LETTER and a SPEED_TEST, both
    inside the full-weight recency band: 30.00 plus 15.00 is 45.00 on the
    CHALLENGE side across two distinct types."""
    caller = submitter_headers or CHALLENGER
    challenge = file_challenge(
        program_id,
        location_id,
        caller,
        challenger_type=challenger_type,
        rationale=rationale,
    )
    append_evidence(
        challenge["id"],
        "SERVICE_DENIAL_LETTER",
        "2026-06-01T00:00:00Z",
        caller,
        description="Denial letter.",
    )
    append_evidence(
        challenge["id"],
        "SPEED_TEST",
        "2026-07-01T00:00:00Z",
        caller,
        description="Speed tests.",
    )
    return read_challenge(challenge["id"])


def triage_challenge(challenge_id, headers=None):
    return get_success_data(
        api_client.triage_challenge(challenge_id, headers or ANALYST)
    )


def close_rebuttal(challenge_id, headers=None):
    return get_success_data(api_client.close_rebuttal(challenge_id, headers or ANALYST))


def setup_under_review_challenge(
    program_id,
    location_id,
    submitter_headers=None,
    deadline_clock="2026-09-10T00:00:00Z",
    challenger_type="COMMUNITY",
):
    """A triaged challenge whose rebuttal window has been closed on the
    deadline branch, leaving it in UNDER_REVIEW at rebuttal_round 1."""
    challenge = setup_community_challenge_meeting_standard(
        program_id, location_id, submitter_headers, challenger_type=challenger_type
    )
    triage_challenge(challenge["id"])
    set_clock(deadline_clock)
    close_rebuttal(challenge["id"])
    return read_challenge(challenge["id"])


# --------------------------------------------------------------------------
# Tier 3: applicants and their capability review
# --------------------------------------------------------------------------


def register_subgrantee(program_id, **overrides):
    return get_success_data(
        api_client.create_subgrantee(
            create_subgrantee_payload(program_id, **overrides), ADMIN
        )
    )


def run_capability_review(subgrantee_id, technical_raw_score=30, headers=None):
    """Open review and record the determination as the same reviewer, since the
    determination compares the caller to capability_reviewer_user_id."""
    reviewer = headers or REVIEWER
    get_success_data(api_client.begin_capability_review(subgrantee_id, reviewer))
    return get_success_data(
        api_client.record_capability_determination(
            subgrantee_id, {"technical_raw_score": technical_raw_score}, reviewer
        )
    )


def setup_qualified_subgrantee(program_id, technical_raw_score=30, **overrides):
    """An applicant declaring 900000 in net assets against a 3000000 request
    with four key personnel and a prior federal award, reviewed at a technical
    raw score of 30: capability_index 90.00 and capability_state QUALIFIED."""
    subgrantee = register_subgrantee(program_id, **overrides)
    return run_capability_review(subgrantee["id"], technical_raw_score)


def setup_remediation_required_subgrantee(
    program_id,
    legal_name="Ridgeway Telephone LLC",
    ein="82-7654321",
    technical_raw_score=30,
    **overrides,
):
    """An applicant declaring 600000 in net assets against a 3000000 request
    with two key personnel and no prior award: capability_index 68.00, which
    lands in the remediation band and yields REMEDIATION_REQUIRED."""
    payload_overrides = {
        "legal_name": legal_name,
        "ein": ein,
        "net_assets_cents": 600000,
        "requested_amount_cents": 3000000,
        "key_personnel_count": 2,
        "has_prior_federal_award": False,
    }
    payload_overrides.update(overrides)
    subgrantee = register_subgrantee(program_id, **payload_overrides)
    return run_capability_review(subgrantee["id"], technical_raw_score)


def submit_remediation(
    subgrantee_id, audited_net_assets_cents, withdrawn_personnel_count, headers=None
):
    return get_success_data(
        api_client.submit_remediation(
            subgrantee_id,
            {
                "audited_net_assets_cents": audited_net_assets_cents,
                "withdrawn_personnel_count": withdrawn_personnel_count,
            },
            headers or make_subgrantee_headers(subgrantee_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 4: applications, claims and submission
# --------------------------------------------------------------------------


def create_application(program_id, subgrantee_id, headers=None, **overrides):
    """Open a draft application. A Subgrantee caller's X-User-ID must equal the
    named subgrantee_id."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(program_id, subgrantee_id, **overrides),
            headers or make_subgrantee_headers(subgrantee_id),
        )
    )


def claim_location(application_id, location_id, subgrantee_id, headers=None, **overrides):
    """Claim one location for a draft application at a declared cost."""
    return get_success_data(
        api_client.create_location_claim(
            create_location_claim_payload(application_id, location_id, **overrides),
            headers or make_subgrantee_headers(subgrantee_id),
        )
    )


def submit_application(application_id, subgrantee_id, headers=None):
    return get_success_data(
        api_client.submit_application(
            application_id, headers or make_subgrantee_headers(subgrantee_id)
        )
    )


def setup_submitted_application(
    program_id,
    subgrantee_id,
    claims,
    application_overrides=None,
):
    """A submitted application with the given claims.

    ``claims`` is a sequence of ``(location_id, claimed_cost_cents)`` pairs.
    Returns ``(application, claim_rows)``.
    """
    application = create_application(
        program_id, subgrantee_id, **(application_overrides or {})
    )
    claim_rows = []
    for location_id, cost in claims:
        claim_rows.append(
            claim_location(
                application["id"],
                location_id,
                subgrantee_id,
                claimed_cost_cents=cost,
            )
        )
    application = submit_application(application["id"], subgrantee_id)
    return application, claim_rows


def advance_program_to_scoring(program_id, clock=TEST_DEFAULTS["POST_WINDOW_CLOCK"]):
    """Move the clock past both window ends, close the challenge window and
    open scoring."""
    set_clock(clock)
    close_challenge_window(program_id)
    return open_scoring(program_id)


# --------------------------------------------------------------------------
# Tier 5: scoring, selection and obligation
# --------------------------------------------------------------------------


def score_application(application_id, headers=None, expected_application_version=None):
    """Produce a score sheet, reading the application's live version first."""
    officer = headers or SCORER
    version = (
        expected_application_version
        if expected_application_version is not None
        else current_application_version(application_id)
    )
    return get_success_data(
        api_client.create_score_sheet(
            create_score_sheet_payload(application_id, version), officer
        )
    )


def select_application(application_id, headers=None):
    return get_success_data(
        api_client.select_application(application_id, headers or ADMIN)
    )


def obligate_award(application_id, headers=None):
    return get_success_data(
        api_client.create_award(create_award_payload(application_id), headers or ADMIN)
    )


def setup_scored_application(
    location_keys=("L2", "L3", "L5"),
    claims=None,
    program_overrides=None,
    application_overrides=None,
    subgrantee_overrides=None,
):
    """The canonical chain through to a FINAL score sheet in a SCORING program.

    ``claims`` is a sequence of ``(location_key, claimed_cost_cents)`` pairs and
    defaults to every ingested location at the canonical 900002 cents.
    Returns a context dict with ``program``, ``locations``, ``location_ids``,
    ``subgrantee``, ``subgrantee_id``, ``application``, ``claims`` and
    ``score_sheet``.
    """
    ctx = setup_challenge_open_program(location_keys, **(program_overrides or {}))
    subgrantee = setup_qualified_subgrantee(
        ctx["program_id"], **(subgrantee_overrides or {})
    )
    if claims is None:
        claims = [
            (key, TEST_DEFAULTS["CANONICAL_CLAIM_COST_CENTS"]) for key in location_keys
        ]
    application, claim_rows = setup_submitted_application(
        ctx["program_id"],
        subgrantee["id"],
        [(ctx["location_ids"][key], cost) for key, cost in claims],
        application_overrides,
    )
    advance_program_to_scoring(ctx["program_id"])
    score_sheet = score_application(application["id"])
    ctx.update(
        {
            "subgrantee": subgrantee,
            "subgrantee_id": subgrantee["id"],
            "application": read_application(application["id"]),
            "application_id": application["id"],
            "claims": claim_rows,
            "claim_ids": [c["id"] for c in claim_rows],
            "score_sheet": score_sheet,
            "program": read_program(ctx["program_id"]),
        }
    )
    return ctx


def setup_obligated_award(**kwargs):
    """The canonical chain through to an OBLIGATED award.

    Adds ``award`` and ``award_id`` to the context returned by
    :func:`setup_scored_application`.
    """
    ctx = setup_scored_application(**kwargs)
    select_application(ctx["application_id"])
    award = obligate_award(ctx["application_id"])
    ctx.update(
        {
            "award": award,
            "award_id": award["id"],
            "application": read_application(ctx["application_id"]),
            "program": read_program(ctx["program_id"]),
        }
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 6: environmental clearance and construction
# --------------------------------------------------------------------------


def open_environmental_review(award_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_environmental_review(
            award_id, create_environmental_review_payload(**overrides), headers or EHP
        )
    )


def record_environmental_determination(award_id, pathway, headers=None, **overrides):
    return get_success_data(
        api_client.record_environmental_determination(
            award_id,
            create_environmental_determination_payload(pathway, **overrides),
            headers or EHP,
        )
    )


def clear_environmental_review(award_id, headers=None):
    return get_success_data(
        api_client.clear_environmental_review(award_id, headers or EHP)
    )


def setup_cleared_environmental_review(award_id):
    """Screening with no consultation obligations, a CATEGORICAL_EXCLUSION
    determination and clearance."""
    open_environmental_review(award_id)
    record_environmental_determination(award_id, "CATEGORICAL_EXCLUSION")
    return clear_environmental_review(award_id)


def authorize_construction(award_id, headers=None):
    return get_success_data(
        api_client.authorize_construction(award_id, headers or ADMIN)
    )


def setup_construction_authorized_award(**kwargs):
    """An obligated award whose review is CLEARED and whose construction has
    been authorised, so every AWARD_BOUND location is UNDER_CONSTRUCTION."""
    ctx = setup_obligated_award(**kwargs)
    setup_cleared_environmental_review(ctx["award_id"])
    ctx["award"] = authorize_construction(ctx["award_id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 7: milestones and disbursement
# --------------------------------------------------------------------------


def add_milestone(award_id, sequence_no, planned_location_ids, headers=None, **overrides):
    return get_success_data(
        api_client.create_milestone(
            award_id,
            create_milestone_payload(sequence_no, planned_location_ids, **overrides),
            headers or ADMIN,
        )
    )


def submit_milestone_evidence(
    award_id, milestone_id, built_location_ids, subgrantee_id, headers=None, **overrides
):
    return get_success_data(
        api_client.submit_milestone_evidence(
            award_id,
            milestone_id,
            submit_milestone_evidence_payload(built_location_ids, **overrides),
            headers or make_subgrantee_headers(subgrantee_id),
        )
    )


def verify_milestone(award_id, milestone_id, outcome="APPROVED", headers=None, **overrides):
    return get_success_data(
        api_client.verify_milestone(
            award_id,
            milestone_id,
            verify_milestone_payload(outcome, **overrides),
            headers or AUDITOR,
        )
    )


def disburse_milestone(award_id, milestone_id, headers=None):
    return get_success_data(
        api_client.disburse_milestone(award_id, milestone_id, headers or ADMIN)
    )


def setup_disbursed_milestone(
    ctx,
    milestone_location_keys=("L2",),
    sequence_no=1,
    evidence_basis="BUILD_PROGRESS",
    invoiced_cost_cents=None,
    verifier_headers=None,
    **milestone_overrides,
):
    """Add a milestone over the named locations, submit build evidence, verify
    it APPROVED and disburse it, which moves the award into IN_CONSTRUCTION.

    Returns the disbursed milestone.
    """
    location_ids = [ctx["location_ids"][k] for k in milestone_location_keys]
    milestone = add_milestone(
        ctx["award_id"],
        sequence_no,
        location_ids,
        evidence_basis=evidence_basis,
        **milestone_overrides,
    )
    evidence_extras = {}
    if invoiced_cost_cents is not None:
        evidence_extras["invoiced_cost_cents"] = invoiced_cost_cents
    submit_milestone_evidence(
        ctx["award_id"],
        milestone["id"],
        location_ids,
        ctx["subgrantee_id"],
        **evidence_extras,
    )
    verify_milestone(
        ctx["award_id"], milestone["id"], "APPROVED", headers=verifier_headers
    )
    return disburse_milestone(ctx["award_id"], milestone["id"])


# --------------------------------------------------------------------------
# Tier 8: deployment audits and clawback
# --------------------------------------------------------------------------


def schedule_compliance_audit(
    award_id, audit_type, window_start, window_end, headers=None, **overrides
):
    """Schedule an audit. The scheduling officer is stamped as
    auditor_user_id; a caller who last verified a milestone on this award may
    not later record the result, so audits are scheduled by a second officer."""
    return get_success_data(
        api_client.create_compliance_audit(
            award_id,
            create_compliance_audit_payload(
                audit_type, window_start, window_end, **overrides
            ),
            headers or AUDITOR_OTHER,
        )
    )


def record_audit_result(
    award_id, audit_id, result, tested_location_ids, headers=None, **overrides
):
    return get_success_data(
        api_client.record_audit_result(
            award_id,
            audit_id,
            record_audit_result_payload(result, tested_location_ids, **overrides),
            headers or AUDITOR_OTHER,
        )
    )


def issue_clawback_notice(award_id, audit_id, headers=None):
    return get_success_data(
        api_client.issue_clawback_notice(award_id, audit_id, headers or AUDITOR_OTHER)
    )


def resolve_clawback(award_id, audit_id, resolution, headers=None, **overrides):
    payload = {"resolution": resolution}
    payload.update(overrides)
    return get_success_data(
        api_client.resolve_clawback(award_id, audit_id, payload, headers or ADMIN)
    )


def setup_failed_audit(
    ctx,
    tested_location_keys,
    failed_location_keys,
    audit_type="SERVICE_AVAILABILITY",
    window_start="2027-01-05T00:00:00Z",
    window_end="2027-01-10T00:00:00Z",
    result_clock="2027-01-15T00:00:00Z",
):
    """Schedule an audit over a closed observation window, move the clock past
    its start and record a FAILED result naming the failed locations.

    Returns the audit row.
    """
    audit = schedule_compliance_audit(
        ctx["award_id"], audit_type, window_start, window_end
    )
    set_clock(result_clock)
    return record_audit_result(
        ctx["award_id"],
        audit["id"],
        "FAILED",
        [ctx["location_ids"][k] for k in tested_location_keys],
        failed_location_ids=[ctx["location_ids"][k] for k in failed_location_keys],
    )


def terminate_award(award_id, terminated_reason, headers=None):
    return get_success_data(
        api_client.terminate_award(
            award_id, {"terminated_reason": terminated_reason}, headers or ADMIN
        )
    )
