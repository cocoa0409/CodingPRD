"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Fixtures use get_success_data() (lenient validator) so setup failures surface
as clear "setup failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_geography_payload,
    create_csa_payload,
    create_training_record_payload,
    create_referral_payload,
    create_incident_payload,
    create_classify_payload,
    create_offense_count_payload,
    create_safety_alert_payload,
    create_decision_payload,
    create_inspection_request_payload,
    create_asr_payload,
    create_compile_payload,
    create_fire_incident_payload,
    create_fire_report_payload,
    create_program_review_payload,
    create_corrective_action_payload,
)
from .test_users import TEST_USERS, make_csa_headers

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CHIEF = TEST_USERS["chief_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Tier 1: State Progression ─────────────────────────────────────────────

def create_geography(name="Main Campus", category="ON_CAMPUS", is_residential_facility=False):
    """Create one ACTIVE Clery geography. Returns geography dict."""
    return get_success_data(api_client.create_geography(
        create_geography_payload(
            name=name, category=category, is_residential_facility=is_residential_facility
        ),
        ADMIN,
    ))


def set_clock(to_iso8601):
    """Advance the logical clock. Returns the clock response payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_draft_incident(geography_id, reported_at="2026-06-01T10:00:00Z",
                          occurred_at="2026-06-01T09:00:00Z", headers=None, **overrides):
    """Create one DRAFT incident. Returns incident dict (version 1)."""
    return get_success_data(api_client.create_incident(
        create_incident_payload(
            geography_id, reported_at=reported_at, occurred_at=occurred_at, **overrides
        ),
        headers or CHIEF,
    ))


def create_submitted_incident(geography_id, **overrides):
    """Create incident and submit it. Returns SUBMITTED incident (version 2)."""
    incident = create_draft_incident(geography_id, **overrides)
    return get_success_data(api_client.submit_incident(incident["id"], CHIEF))


def create_under_classification_incident(geography_id, **overrides):
    """Create → submit → begin-classification. Returns UNDER_CLASSIFICATION incident
    (version 3, ready for classify with expected_incident_version == 3)."""
    incident = create_submitted_incident(geography_id, **overrides)
    return get_success_data(api_client.begin_classification(incident["id"], COORD))


def classify_incident(incident, geography_id, offense_counts):
    """Classify an incident currently in UNDER_CLASSIFICATION or
    UNDER_RECLASSIFICATION. `incident` must be the freshest read (its version is
    used as expected_incident_version). Returns the CLASSIFIED incident."""
    return get_success_data(api_client.classify_incident(
        incident["id"],
        create_classify_payload(
            geography_id,
            expected_incident_version=incident["version"],
            offense_counts=offense_counts,
        ),
        COORD,
    ))


def create_classified_incident(geography_id, offense_counts=None, **overrides):
    """Create → submit → begin-classification → classify. Returns CLASSIFIED
    incident (version 4)."""
    incident = create_under_classification_incident(geography_id, **overrides)
    if offense_counts is None:
        offense_counts = [create_offense_count_payload()]
    return classify_incident(incident, geography_id, offense_counts)


def create_unfounded_incident(geography_id, justification="Fabricated report confirmed",
                              offense_counts=None, **overrides):
    """Create → classify → unfound. Returns UNFOUNDED incident."""
    incident = create_classified_incident(geography_id, offense_counts=offense_counts, **overrides)
    return get_success_data(api_client.unfound_incident(
        incident["id"], {"justification": justification}, CHIEF
    ))


def create_active_csa(completed_at="2026-06-01T10:00:00Z", score=90, **csa_overrides):
    """Register a CSA and record one passing training record so the CSA is ACTIVE.
    Returns (csa, training_record)."""
    csa = get_success_data(api_client.create_csa(create_csa_payload(**csa_overrides), ADMIN))
    record = get_success_data(api_client.create_training_record(
        csa["id"],
        create_training_record_payload(completed_at=completed_at, score=score),
        ADMIN,
    ))
    csa = get_success_data(api_client.get_csa(csa["id"], ADMIN))
    return csa, record


def create_pending_csa(**csa_overrides):
    """Register a CSA that stays PENDING_TRAINING. Returns csa dict."""
    return get_success_data(api_client.create_csa(create_csa_payload(**csa_overrides), ADMIN))


def create_received_referral(csa, geography_id, **overrides):
    """An ACTIVE CSA files a referral. Caller identity is threaded through the
    CSA's own id (ownership-gated endpoint per PRD §2.1). Returns RECEIVED referral."""
    return get_success_data(api_client.create_referral(
        create_referral_payload(geography_id, **overrides),
        make_csa_headers(csa["id"]),
    ))


def create_pending_alert(incident, alert_type="TIMELY_WARNING"):
    """Open a SafetyAlert on an incident that is at least SUBMITTED.
    Returns PENDING_REVIEW alert."""
    return get_success_data(api_client.create_safety_alert(
        incident["id"], create_safety_alert_payload(alert_type=alert_type), COORD
    ))


def create_decided_alert(incident, decision="ISSUE", decision_rationale="Continuing threat",
                         alert_type="TIMELY_WARNING"):
    """Open + decide a SafetyAlert. Returns the decided alert."""
    alert = create_pending_alert(incident, alert_type=alert_type)
    return get_success_data(api_client.decide_alert(
        alert["id"],
        create_decision_payload(decision=decision, decision_rationale=decision_rationale),
        COORD,
    ))


def create_authorized_alert(incident, alert_type="TIMELY_WARNING"):
    """Open + decide ISSUE + authorize. Returns AUTHORIZED alert."""
    alert = create_decided_alert(incident, decision="ISSUE", alert_type=alert_type)
    return get_success_data(api_client.authorize_alert(alert["id"], CHIEF))


# ─── Tier 2: Log entries ───────────────────────────────────────────────────

def get_log_entry_for_incident(incident_id, headers=None):
    """Read the single DailyCrimeLogEntry of a submitted incident via the log
    list. Staff callers pass include_unfounded=true so entries of UNFOUNDED /
    WITHDRAWN / DRAFT incidents are surfaced (PRD §3.4)."""
    entries = get_success_data(api_client.list_crime_log(
        headers or CHIEF,
        params={"incident_id": incident_id, "include_unfounded": "true"},
    ))
    items = entries if isinstance(entries, list) else entries.get("items", entries)
    assert isinstance(items, list) and len(items) >= 1, (
        f"Setup failed: expected a log entry for incident {incident_id}"
    )
    return items[0]


def list_log_for_incident(incident_id, headers=None):
    """Return the full paginated list payload for one incident's log entries."""
    return get_success_data(api_client.list_crime_log(
        headers or CHIEF,
        params={"incident_id": incident_id, "include_unfounded": "true"},
    ))


# ─── Tier 3: ASR lifecycle shortcuts ───────────────────────────────────────

def create_asr(report_year=2026):
    """Create one ASR shell in COLLECTING (statistics_version 0)."""
    return get_success_data(api_client.create_asr(create_asr_payload(report_year=report_year), ADMIN))


def compile_asr(asr, variant="FINAL"):
    """Compile an ASR using its current version as the OCC field.
    Returns the compiled ASR."""
    return get_success_data(api_client.compile_asr(
        asr["id"],
        create_compile_payload(expected_report_version=asr["version"], variant=variant),
        COORD,
    ))


def create_compiled_asr(report_year=2026, variant="FINAL"):
    """Create an ASR shell and compile it once. Returns compiled ASR."""
    asr = create_asr(report_year=report_year)
    return compile_asr(asr, variant=variant)


def create_published_asr(report_year=2026):
    """Create ASR → FINAL compile → submit-review → publish. Returns PUBLISHED ASR."""
    asr = create_compiled_asr(report_year=report_year, variant="FINAL")
    asr = get_success_data(api_client.submit_asr_review(asr["id"], COORD))
    return get_success_data(api_client.publish_asr(asr["id"], CHIEF))


def list_current_statistic_lines(asr_id, headers=None, params=None):
    """List statistic lines of a report (default CURRENT snapshot)."""
    merged = dict(params or {})
    return get_success_data(api_client.list_statistic_lines(
        asr_id, headers or COORD, params=merged
    ))


# ─── Tier 4: Fire report lifecycle ─────────────────────────────────────────

def create_fire_report(report_year=2026):
    """Create one fire safety report shell (DRAFT)."""
    return get_success_data(api_client.create_fire_report(
        create_fire_report_payload(report_year=report_year), ADMIN
    ))


def create_fire_incident(geography_id, **overrides):
    """Report one fire incident (REPORTED)."""
    return get_success_data(api_client.create_fire_incident(
        create_fire_incident_payload(geography_id, **overrides), CHIEF
    ))


def finalize_fire_incident(fire_id, adjudicated_damage_dollars):
    """Finalize a fire incident with the adjudicated damage value."""
    return get_success_data(api_client.finalize_fire_incident(
        fire_id, {"adjudicated_damage_dollars": adjudicated_damage_dollars}, CHIEF
    ))


def create_compiled_fire_report(report_year=2026):
    """Create a fire report shell and compile it once. Returns COMPILED report."""
    fsr = create_fire_report(report_year=report_year)
    return get_success_data(api_client.compile_fire_report(fsr["id"], COORD))


def create_published_fire_report(report_year=2026):
    """Create fire report → compile → publish. Returns PUBLISHED report."""
    fsr = create_compiled_fire_report(report_year=report_year)
    return get_success_data(api_client.publish_fire_report(fsr["id"], CHIEF))


# ─── Tier 5: Program review lifecycle ──────────────────────────────────────

def create_program_review(scope_year_start=2024, scope_year_end=2025):
    """Open one program review (OPENED)."""
    return get_success_data(api_client.create_program_review(
        create_program_review_payload(
            scope_year_start=scope_year_start, scope_year_end=scope_year_end
        ),
        REVIEWER,
    ))


def create_review_in_findings_issued(scope_year_start=2024, scope_year_end=2025):
    """Create → advance. Returns review in FINDINGS_ISSUED."""
    review = create_program_review(scope_year_start, scope_year_end)
    return get_success_data(api_client.advance_review(review["id"], REVIEWER))


def create_review_in_corrective_action(scope_year_start=2024, scope_year_end=2025,
                                       action_overrides=None):
    """Create → advance → one corrective action → advance.
    Returns (review in CORRECTIVE_ACTION, action in OPEN)."""
    review = create_review_in_findings_issued(scope_year_start, scope_year_end)
    action = get_success_data(api_client.create_corrective_action(
        review["id"], create_corrective_action_payload(**(action_overrides or {})), REVIEWER
    ))
    review = get_success_data(api_client.advance_review(review["id"], REVIEWER))
    return review, action


def create_closed_review(scope_year_start=2022, scope_year_end=2023,
                         action_overrides=None):
    """Full lifecycle: create → findings → action → corrective → submit →
    verify (auto-advance) → close. Returns (CLOSED review, VERIFIED action)."""
    review, action = create_review_in_corrective_action(
        scope_year_start, scope_year_end, action_overrides=action_overrides
    )
    get_success_data(api_client.submit_corrective_action(
        action["id"], {"resolution_summary": "Remediated"}, COORD
    ))
    get_success_data(api_client.verify_corrective_action(action["id"], REVIEWER))
    review = get_success_data(api_client.get_program_review(review["id"], REVIEWER))
    review = get_success_data(api_client.advance_review(review["id"], REVIEWER))
    return review, get_success_data(
        api_client.list_corrective_actions(review["id"], REVIEWER)
    )[0]


# ─── Tier 6: Inspection requests ───────────────────────────────────────────

def create_inspection_request(from_date, to_date, requester_name="Pat Public",
                              requester_contact="pat@example.com"):
    """File a public log-inspection request as Anonymous."""
    return get_success_data(api_client.create_inspection_request(
        create_inspection_request_payload(
            requester_name=requester_name, requester_contact=requester_contact,
            from_date=from_date, to_date=to_date,
        ),
        ANON,
    ))


def setup_pending_inspection_request():
    """Submitted incident occurred 2026-05-01 (older than 60 days at request time);
    clock at 2026-08-03T10:00:00Z (Monday). Returns (PENDING request, incident)."""
    geo = create_geography(name="Inspection Lot")
    incident = create_submitted_incident(
        geo["id"], reported_at="2026-05-01T09:00:00Z", occurred_at="2026-05-01T08:00:00Z"
    )
    set_clock("2026-08-03T10:00:00Z")
    request = create_inspection_request(from_date="2026-05-01", to_date="2026-05-02",
                                        requester_name="Jo", requester_contact="jo@example.com")
    return request, incident
