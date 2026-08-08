"""Composite setup helpers.

Every helper builds its state exclusively through declared endpoints, because
the server starts empty before each test. Helpers use the lenient success
validator so a broken precondition surfaces as a setup failure rather than as a
confusing assertion inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    HIGH_REQUIRED_ELEMENTS,
    HIGH_TIER_REFERRAL_INPUTS,
    MODERATE_TIER_REFERRAL_INPUTS,
    SEVERE_TIER_REFERRAL_INPUTS,
)
from .factories import (
    create_facility_payload,
    create_navigator_payload,
    create_patient_payload,
    create_payer_payload,
    create_referral_payload,
    next_mrn,
)
from .test_users import (
    make_billing_specialist_headers,
    make_care_navigator_headers,
    make_clinician_headers,
    make_intake_coordinator_headers,
    make_program_admin_headers,
)

DEFAULT_SETUP_CLOCK = "2026-05-01T16:00:00Z"
DEFAULT_VISIT_START = "2026-05-05T15:00:00Z"
DEFAULT_VISIT_END = "2026-05-05T16:00:00Z"
DEFAULT_VISIT_COMPLETED_AT = "2026-05-05T16:00:00Z"
DEFAULT_SERVICE_PERIOD_CLOSE_AT = "2026-05-31T01:00:00Z"

ADMIN = make_program_admin_headers()
INTAKE = make_intake_coordinator_headers()
CLINICIAN = make_clinician_headers("clin-1")
CLINICIAN_2 = make_clinician_headers("clin-2")
BILLER_PREPARER = make_billing_specialist_headers("bill-prep-1")
BILLER_SUBMITTER = make_billing_specialist_headers("bill-sub-1")

TIER_INPUTS = {
    "HIGH": HIGH_TIER_REFERRAL_INPUTS,
    "MODERATE": MODERATE_TIER_REFERRAL_INPUTS,
    "SEVERE": SEVERE_TIER_REFERRAL_INPUTS,
}


# ---------------------------------------------------------------------------
# Tier 0: clock and reference data
# ---------------------------------------------------------------------------


def set_clock(instant, api=api_client):
    """Move the logical clock. Every deadline is evaluated against it."""
    return get_success_data(api.set_clock({"to_iso8601": instant}, ADMIN))


def declare_holidays(dates, api=api_client):
    return get_success_data(api.set_holidays({"holiday_dates": list(dates)}, ADMIN))


def create_facility(api=api_client, **overrides):
    return get_success_data(api.create_facility(create_facility_payload(**overrides), ADMIN))


def create_payer(api=api_client, **overrides):
    return get_success_data(api.create_payer(create_payer_payload(**overrides), ADMIN))


def create_navigator(api=api_client, **overrides):
    return get_success_data(
        api.create_navigator(create_navigator_payload(**overrides), ADMIN)
    )


def create_patient(api=api_client, **overrides):
    return get_success_data(api.create_patient(create_patient_payload(**overrides), ADMIN))


def setup_program(
    clock=DEFAULT_SETUP_CLOCK,
    facility_overrides=None,
    payer_overrides=None,
    navigator_overrides=None,
    api=api_client,
):
    """Clock + one facility + one payer + one navigator.

    Returns a context dict carrying the created rows and the navigator headers
    that ownership-gated calls must use.
    """
    set_clock(clock, api=api)
    facility = create_facility(api=api, **(facility_overrides or {}))
    payer = create_payer(api=api, **(payer_overrides or {}))
    navigator = create_navigator(api=api, **(navigator_overrides or {}))
    return {
        "api": api,
        "facility": facility,
        "facility_id": facility["id"],
        "payer": payer,
        "payer_id": payer["id"],
        "navigator": navigator,
        "navigator_id": navigator["id"],
        "nav_headers": make_care_navigator_headers(navigator["id"]),
    }


def add_navigator(ctx, **overrides):
    """Register an extra navigator and return (row, headers) bound to its id."""
    navigator = create_navigator(api=ctx["api"], **overrides)
    return navigator, make_care_navigator_headers(navigator["id"])


# ---------------------------------------------------------------------------
# Tier 1: referral and episode creation
# ---------------------------------------------------------------------------


def create_referral(ctx, patient_id=None, tier="HIGH", **overrides):
    """Record a discharge referral. Creation performs no eligibility screening."""
    api = ctx["api"]
    if patient_id is None:
        patient_id = create_patient(api=api, external_mrn=next_mrn())["id"]
    payload = create_referral_payload(
        patient_id, ctx["facility_id"], ctx["payer_id"], **TIER_INPUTS[tier]
    )
    payload.update(overrides)
    referral = get_success_data(api.create_referral(payload, INTAKE))
    referral["_patient_id"] = patient_id
    return referral


def accept_referral(ctx, referral, navigator_id=None):
    """Run the intake gauntlet and mint the care episode."""
    api = ctx["api"]
    navigator_id = navigator_id or ctx["navigator_id"]
    accepted = get_success_data(
        api.accept_referral(referral["id"], {"navigator_id": navigator_id}, INTAKE)
    )
    episode_id = accepted["created_episode_id"]
    episode = get_success_data(api.get_episode(episode_id, ADMIN))
    return {
        "referral": accepted,
        "referral_id": accepted["id"],
        "patient_id": episode["patient_id"],
        "episode": episode,
        "episode_id": episode_id,
        "navigator_id": navigator_id,
        "nav_headers": make_care_navigator_headers(navigator_id),
    }


def setup_episode(ctx, tier="HIGH", patient_id=None, navigator_id=None, **referral_overrides):
    """Referral -> accept -> episode in INTAKE. Returns an episode context."""
    referral = create_referral(ctx, patient_id=patient_id, tier=tier, **referral_overrides)
    return accept_referral(ctx, referral, navigator_id=navigator_id)


def setup_program_with_episode(tier="HIGH", clock=DEFAULT_SETUP_CLOCK, **kwargs):
    """The most common preamble: programme reference data plus one episode."""
    program_kwargs = {
        k: kwargs.pop(k)
        for k in ("facility_overrides", "payer_overrides", "navigator_overrides")
        if k in kwargs
    }
    ctx = setup_program(clock=clock, **program_kwargs)
    ep = setup_episode(ctx, tier=tier, **kwargs)
    return ctx, ep


def episode_assessments(ctx, episode_id):
    """Every risk assessment of an episode, oldest first."""
    resp = ctx["api"].list_risk_assessments(ADMIN, params={"episode_id": episode_id})
    return get_success_data(resp)


def current_assessment(ctx, episode_id):
    """The single assessment of an episode whose is_current reads true."""
    rows = [r for r in episode_assessments(ctx, episode_id) if r.get("is_current")]
    assert len(rows) == 1, (
        f"exactly one assessment per episode is ever current, found {len(rows)}"
    )
    return rows[0]


def refresh_episode(ctx, ep):
    ep["episode"] = get_success_data(ctx["api"].get_episode(ep["episode_id"], ADMIN))
    return ep["episode"]


def read_episode(ctx, episode_id):
    return get_success_data(ctx["api"].get_episode(episode_id, ADMIN))


def read_navigator(ctx, navigator_id):
    return get_success_data(ctx["api"].get_navigator(navigator_id, ADMIN))


def read_patient(ctx, patient_id):
    return get_success_data(ctx["api"].get_patient(patient_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: interactive contact
# ---------------------------------------------------------------------------


def log_attempt(ctx, ep, modality="PHONE", **overrides):
    payload = {"modality": modality}
    payload.update(overrides)
    return get_success_data(
        ctx["api"].log_contact_attempt(ep["episode_id"], payload, ep["nav_headers"])
    )


def disposition_attempt(ctx, ep, attempt_id, outcome):
    return get_success_data(
        ctx["api"].disposition_contact_attempt(
            attempt_id, {"outcome": outcome}, ep["nav_headers"]
        )
    )


def connect_contact(ctx, ep, at=None):
    """Log one PHONE attempt and disposition it CONNECTED, establishing
    successful interactive contact so the visit may later be completed."""
    if at is not None:
        set_clock(at, api=ctx["api"])
    attempt = log_attempt(ctx, ep, "PHONE")
    disposition_attempt(ctx, ep, attempt["id"], "CONNECTED")
    return attempt


# ---------------------------------------------------------------------------
# Tier 3: medication reconciliation
# ---------------------------------------------------------------------------


def open_medrec(ctx, ep, headers=CLINICIAN):
    return get_success_data(
        ctx["api"].open_med_reconciliation(ep["episode_id"], headers)
    )


def read_medrec(ctx, medrec_id, headers=CLINICIAN):
    return get_success_data(ctx["api"].get_med_reconciliation(medrec_id, headers))


def append_discrepancy(ctx, medrec_id, severity="LOW", medication_name="metformin",
                       discrepancy_type="DOSE_MISMATCH", headers=CLINICIAN):
    """Append a line item using the reconciliation's live version, which the
    optimistic-concurrency check on this endpoint requires."""
    current = read_medrec(ctx, medrec_id, headers)
    payload = {
        "medication_name": medication_name,
        "discrepancy_type": discrepancy_type,
        "severity": severity,
        "expected_med_reconciliation_version": current["version"],
    }
    return get_success_data(ctx["api"].append_discrepancy(medrec_id, payload, headers))


def complete_medrec(ctx, medrec_id, headers=CLINICIAN):
    return get_success_data(
        ctx["api"].complete_med_reconciliation(medrec_id, headers)
    )


def setup_completed_medrec(ctx, ep, headers=CLINICIAN):
    """Open the episode's reconciliation and complete it with zero line items."""
    medrec = open_medrec(ctx, ep, headers)
    complete_medrec(ctx, medrec["id"], headers)
    return read_medrec(ctx, medrec["id"], headers)


# ---------------------------------------------------------------------------
# Tier 4: the face-to-face visit
# ---------------------------------------------------------------------------


def book_visit(ctx, ep, start=DEFAULT_VISIT_START, end=DEFAULT_VISIT_END,
               navigator_id=None, headers=None):
    payload = {
        "navigator_id": navigator_id or ep["navigator_id"],
        "scheduled_start": start,
        "scheduled_end": end,
    }
    return get_success_data(
        ctx["api"].book_visit(ep["episode_id"], payload, headers or ep["nav_headers"])
    )


def confirm_visit(ctx, ep, visit_id):
    return get_success_data(ctx["api"].confirm_visit(visit_id, ep["nav_headers"]))


def complete_visit(ctx, visit_id, elements=None, at=None, headers=CLINICIAN):
    if at is not None:
        set_clock(at, api=ctx["api"])
    payload = {"documented_elements": list(elements or HIGH_REQUIRED_ELEMENTS)}
    return get_success_data(ctx["api"].complete_visit(visit_id, payload, headers))


def attest_visit(ctx, visit_id, headers=CLINICIAN):
    return get_success_data(ctx["api"].attest_visit(visit_id, headers))


def read_visit(ctx, visit_id, headers=None):
    return get_success_data(ctx["api"].get_visit(visit_id, headers or ADMIN))


def setup_confirmed_visit(ctx, ep, start=DEFAULT_VISIT_START, end=DEFAULT_VISIT_END):
    """Book the slot and confirm the appointment with the patient."""
    visit = book_visit(ctx, ep, start=start, end=end)
    confirm_visit(ctx, ep, visit["id"])
    return read_visit(ctx, visit["id"])


def setup_attested_visit(
    ctx,
    ep,
    start=DEFAULT_VISIT_START,
    end=DEFAULT_VISIT_END,
    completed_at=DEFAULT_VISIT_COMPLETED_AT,
    elements=None,
    clinician=CLINICIAN,
):
    """Contact must already have succeeded and the reconciliation completed.

    Books, confirms, completes and attests the visit, returning the attested row.
    """
    visit = setup_confirmed_visit(ctx, ep, start=start, end=end)
    complete_visit(ctx, visit["id"], elements=elements, at=completed_at, headers=clinician)
    attest_visit(ctx, visit["id"], headers=clinician)
    return read_visit(ctx, visit["id"])


# ---------------------------------------------------------------------------
# Tier 5: service-period closure and billing
# ---------------------------------------------------------------------------


def close_service_period(ctx, ep, at=DEFAULT_SERVICE_PERIOD_CLOSE_AT):
    if at is not None:
        set_clock(at, api=ctx["api"])
    return get_success_data(
        ctx["api"].close_service_period(ep["episode_id"], ADMIN)
    )


def prepare_claim(ctx, ep, visit_id, headers=BILLER_PREPARER):
    return get_success_data(
        ctx["api"].prepare_claim(ep["episode_id"], {"visit_id": visit_id}, headers)
    )


def submit_claim(ctx, claim_id, headers=BILLER_SUBMITTER):
    return get_success_data(ctx["api"].submit_claim(claim_id, headers))


def adjudicate_claim(ctx, claim_id, outcome, denial_reason_code=None):
    payload = {"outcome": outcome}
    if denial_reason_code is not None:
        payload["denial_reason_code"] = denial_reason_code
    return get_success_data(ctx["api"].adjudicate_claim(claim_id, payload, ADMIN))


def read_claim(ctx, claim_id):
    return get_success_data(ctx["api"].get_claim(claim_id, ADMIN))


def setup_billable_episode(
    tier="HIGH",
    clock=DEFAULT_SETUP_CLOCK,
    visit_start=DEFAULT_VISIT_START,
    visit_end=DEFAULT_VISIT_END,
    visit_completed_at=DEFAULT_VISIT_COMPLETED_AT,
    elements=None,
    close_at=DEFAULT_SERVICE_PERIOD_CLOSE_AT,
    payer_overrides=None,
    contact_at=None,
    **kwargs
):
    """Full preamble to a claim-ready episode.

    Programme reference data, an accepted referral, successful interactive
    contact, a COMPLETED zero-item reconciliation, an attested face-to-face
    visit and a closed service period.

    Returns (ctx, ep, visit).
    """
    ctx = setup_program(
        clock=clock,
        payer_overrides=payer_overrides,
        navigator_overrides=kwargs.pop("navigator_overrides", None),
        facility_overrides=kwargs.pop("facility_overrides", None),
    )
    ep = setup_episode(ctx, tier=tier, **kwargs)
    connect_contact(ctx, ep, at=contact_at)
    setup_completed_medrec(ctx, ep)
    visit = setup_attested_visit(
        ctx,
        ep,
        start=visit_start,
        end=visit_end,
        completed_at=visit_completed_at,
        elements=elements,
    )
    if close_at is not None:
        close_service_period(ctx, ep, at=close_at)
    refresh_episode(ctx, ep)
    return ctx, ep, visit


def setup_prepared_claim(**kwargs):
    """Everything setup_billable_episode builds, plus a PREPARED claim.

    Returns (ctx, ep, visit, claim).
    """
    ctx, ep, visit = setup_billable_episode(**kwargs)
    claim = prepare_claim(ctx, ep, visit["id"])
    return ctx, ep, visit, claim


def setup_submitted_claim(**kwargs):
    """A claim submitted by an identifier distinct from the preparer.

    Returns (ctx, ep, visit, claim).
    """
    ctx, ep, visit, claim = setup_prepared_claim(**kwargs)
    claim = submit_claim(ctx, claim["id"])
    return ctx, ep, visit, claim


# ---------------------------------------------------------------------------
# Tier 6: barriers, red flags, readmissions and handoffs
# ---------------------------------------------------------------------------


def raise_barrier(ctx, ep, barrier_type="TRANSPORTATION", description="no ride to clinic"):
    payload = {"barrier_type": barrier_type, "description": description}
    return get_success_data(
        ctx["api"].raise_barrier(ep["episode_id"], payload, ep["nav_headers"])
    )


def read_barrier(ctx, barrier_id):
    return get_success_data(ctx["api"].get_barrier(barrier_id, ADMIN))


def raise_red_flag(ctx, ep, category="CLINICAL_SYMPTOM", initial_tier="TIER_2",
                   headers=None):
    payload = {"category": category, "initial_tier": initial_tier}
    return get_success_data(
        ctx["api"].raise_red_flag(
            ep["episode_id"], payload, headers or ep["nav_headers"]
        )
    )


def read_red_flag(ctx, red_flag_id):
    return get_success_data(ctx["api"].get_red_flag(red_flag_id, ADMIN))


def run_sweep(ctx, ep):
    return get_success_data(ctx["api"].run_sla_sweep(ep["episode_id"], ADMIN))


def record_readmission(ctx, ep, readmission_date, classification):
    payload = {"readmission_date": readmission_date, "classification": classification}
    return get_success_data(
        ctx["api"].record_readmission(ep["episode_id"], payload, ADMIN)
    )


def read_readmission(ctx, readmission_id):
    return get_success_data(ctx["api"].get_readmission(readmission_id, ADMIN))


def propose_handoff(ctx, ep, to_navigator_id, handoff_type="INTERNAL_NAVIGATOR",
                    expected_episode_version=None, headers=None):
    """Read the episode's live version unless the caller pins a stale one."""
    if expected_episode_version is None:
        expected_episode_version = read_episode(ctx, ep["episode_id"])["version"]
    payload = {
        "to_navigator_id": to_navigator_id,
        "handoff_type": handoff_type,
        "expected_episode_version": expected_episode_version,
    }
    return get_success_data(
        ctx["api"].propose_handoff(
            ep["episode_id"], payload, headers or ep["nav_headers"]
        )
    )


def respond_handoff(ctx, handoff_id, responder_headers, response="ACCEPT",
                    decline_reason=None):
    payload = {"response": response}
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    return get_success_data(
        ctx["api"].respond_handoff(handoff_id, payload, responder_headers)
    )


def read_handoff(ctx, handoff_id):
    return get_success_data(ctx["api"].get_handoff(handoff_id, ADMIN))


def handoff_episode_to(ctx, ep, to_navigator, to_headers):
    """Propose and accept a handoff, moving accountability to another navigator."""
    handoff = propose_handoff(ctx, ep, to_navigator["id"])
    respond_handoff(ctx, handoff["id"], to_headers, "ACCEPT")
    return handoff


__all__ = [name for name in dir() if not name.startswith("_")]
