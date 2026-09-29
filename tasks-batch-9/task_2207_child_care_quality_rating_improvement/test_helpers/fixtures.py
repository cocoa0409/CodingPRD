"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only, because each test starts against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SUBSCALE_CODES
from .factories import (
    CANONICAL_DOMAINS,
    DOMAIN_CODES,
    all_six_scores,
    certify_observer_payload,
    create_coaching_allocation_payload,
    create_coaching_session_payload,
    create_expenditure_payload,
    create_improvement_grant_payload,
    create_observation_visit_payload,
    create_observer_payload,
    create_provider_payload,
    create_rating_cycle_payload,
    create_self_assessment_payload,
    create_staff_credential_payload,
    create_subsidy_claim_payload,
    documentation_for,
    next_staff_registry_id,
    points_map,
    registry_link_payload,
    score_payload,
    verification_approve_payload,
)
from .test_users import (
    ADMIN_USER_ID,
    COACH_USER_ID,
    TEST_USERS,
    make_admin_headers,
    make_coach_headers,
    make_observer_headers,
    make_provider_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# --- Tier 1: primitives -----------------------------------------------------


def set_clock(to_iso8601: str):
    """Move the server's logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_expiry_run():
    return get_success_data(api_client.run_expiry_run(ADMIN))


def declare_domains(domains=None) -> list:
    """Declare the five standard domains; returns the created rows."""
    rows = []
    for spec in (domains if domains is not None else CANONICAL_DOMAINS):
        rows.append(get_success_data(api_client.create_standard_domain(dict(spec), ADMIN)))
    return rows


def create_applied_provider(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(create_provider_payload(**overrides), ADMIN)
    )


def create_enrolled_provider(**overrides) -> dict:
    """Register a provider application and approve it, leaving it ENROLLED."""
    provider = create_applied_provider(**overrides)
    return get_success_data(
        api_client.decide_enrollment(provider["id"], {"decision": "APPROVE"}, ADMIN)
    )


def add_credential(provider_id, registry_status="VERIFIED", expires_on="2027-06-30",
                   verified_on="2026-07-01", **overrides) -> dict:
    """Register one staff credential and optionally record the registry answer."""
    credential = get_success_data(
        api_client.create_staff_credential(
            provider_id, create_staff_credential_payload(**overrides), ADMIN
        )
    )
    if registry_status is None or registry_status == "UNLINKED":
        return credential
    payload = {"registry_status": registry_status}
    if registry_status == "VERIFIED":
        payload["verified_on"] = verified_on
        payload["expires_on"] = expires_on
    return get_success_data(api_client.registry_link(credential["id"], payload, ADMIN))


def provider_version(provider_id) -> int:
    return get_success_data(api_client.get_provider(provider_id, ADMIN))["version"]


def open_cycle(provider_id, cycle_type="INITIAL", expected_version=None) -> dict:
    """Open a rating cycle as the owning provider, reading its current version first."""
    version = expected_version if expected_version is not None else provider_version(provider_id)
    return get_success_data(
        api_client.create_rating_cycle(
            provider_id,
            create_rating_cycle_payload(version, cycle_type),
            make_provider_headers(provider_id),
        )
    )


def submit_self_assessment(provider_id, cycle_id, claimed=None, documentation=None) -> dict:
    return get_success_data(
        api_client.create_self_assessment(
            cycle_id,
            create_self_assessment_payload(claimed=claimed, documentation=documentation),
            make_provider_headers(provider_id),
        )
    )


def verify_self_assessment(self_assessment_id, verified=None) -> dict:
    return get_success_data(
        api_client.decide_verification(
            self_assessment_id, verification_approve_payload(verified=verified), ADMIN
        )
    )


def create_reliable_observer(full_name="Lead Observer One", anchor_agreement_pct=92.00,
                             certified_until="2027-06-30", tool_code="ERS_EARLY_CHILDHOOD") -> dict:
    observer = get_success_data(
        api_client.create_observer(
            create_observer_payload(full_name=full_name, tool_code=tool_code), ADMIN
        )
    )
    return get_success_data(
        api_client.certify_observer(
            observer["id"],
            certify_observer_payload(anchor_agreement_pct, certified_until),
            ADMIN,
        )
    )


def create_provisional_observer(full_name="Provisional Observer") -> dict:
    return get_success_data(
        api_client.create_observer(create_observer_payload(full_name=full_name), ADMIN)
    )


def schedule_visit(cycle_id, lead_observer_id, window_start="2026-08-06T09:00:00Z",
                   window_end="2026-08-06T13:00:00Z", secondary_observer_id=None) -> dict:
    return get_success_data(
        api_client.create_observation_visit(
            cycle_id,
            create_observation_visit_payload(
                lead_observer_id, window_start, window_end, secondary_observer_id
            ),
            ADMIN,
        )
    )


def enter_six_scores(visit_id, observer_id, raw_score=4.0, per_subscale=None) -> list:
    """Enter a current row for all six subscale codes under one observer."""
    rows = []
    for code in SUBSCALE_CODES:
        value = per_subscale.get(code, raw_score) if per_subscale else raw_score
        rows.append(
            get_success_data(
                api_client.submit_score(
                    visit_id, score_payload(code, value), make_observer_headers(observer_id)
                )
            )
        )
    return rows


def finalize_visit(visit_id) -> dict:
    return get_success_data(api_client.finalize_visit(visit_id, ADMIN))


def award_cycle(cycle_id, score_variant="FINAL") -> dict:
    return get_success_data(
        api_client.award_cycle(cycle_id, {"score_variant": score_variant}, ADMIN)
    )


def publish_cycle(cycle_id) -> dict:
    return get_success_data(api_client.publish_cycle(cycle_id, ADMIN))


# --- Tier 2/3: the rating spine ---------------------------------------------

#: Default clock stops used by the spine builder.
SPINE_CLOCK_ENROL = "2026-08-03T00:00:00Z"
SPINE_CLOCK_CYCLE = "2026-08-05T00:00:00Z"
SPINE_WINDOW_START = "2026-08-06T09:00:00Z"
SPINE_WINDOW_END = "2026-08-06T13:00:00Z"
SPINE_CLOCK_SCORING = "2026-08-06T09:00:00Z"
SPINE_CLOCK_AWARD = "2026-08-11T00:00:00Z"
SPINE_CLOCK_PUBLISH = "2026-08-21T00:00:00Z"


def build_rating_spine(
    stop_at="AWARDED",
    domains=None,
    provider_overrides=None,
    credentials=None,
    claimed=None,
    verified=None,
    raw_score=4.0,
    lead_per_subscale=None,
    secondary_per_subscale=None,
    with_secondary=False,
    secondary_raw_score=None,
    window_start=SPINE_WINDOW_START,
    window_end=SPINE_WINDOW_END,
    score_variant="FINAL",
    cycle_type="INITIAL",
    enrol_clock=SPINE_CLOCK_ENROL,
    cycle_clock=SPINE_CLOCK_CYCLE,
    scoring_clock=None,
    award_clock=SPINE_CLOCK_AWARD,
    activation_clock="2026-09-01T00:00:00Z",
):
    """Walk the whole rating spine and stop at the requested stage.

    ``stop_at`` is one of ENROLLED, DRAFT, SELF_ASSESSMENT_SUBMITTED,
    DOCS_VERIFIED, OBSERVATION_SCHEDULED, SCORES_ENTERED, RELIABILITY_CHECK,
    OBSERVATION_FINALIZED, AWARDED, ACTIVE or PUBLISHED.

    Returns a dict with keys: provider, cycle, self_assessment, lead, secondary,
    visit, provider_headers.
    """
    ctx = {"provider": None, "cycle": None, "self_assessment": None,
           "lead": None, "secondary": None, "visit": None}

    set_clock(enrol_clock)
    declare_domains(domains)
    provider = create_enrolled_provider(**(provider_overrides or {}))
    ctx["provider"] = provider
    ctx["provider_headers"] = make_provider_headers(provider["id"])

    for spec in (credentials if credentials is not None else [
        {"role_type": "DIRECTOR", "credential_level": 4, "fte": 1.00},
    ]):
        spec = dict(spec)
        registry_status = spec.pop("registry_status", "VERIFIED")
        expires_on = spec.pop("expires_on", "2027-06-30")
        spec.setdefault("staff_registry_id", next_staff_registry_id())
        add_credential(provider["id"], registry_status=registry_status,
                       expires_on=expires_on, **spec)
    ctx["provider"] = get_success_data(api_client.get_provider(provider["id"], ADMIN))
    if stop_at == "ENROLLED":
        return ctx

    set_clock(cycle_clock)
    cycle = open_cycle(provider["id"], cycle_type)
    ctx["cycle"] = cycle
    if stop_at == "DRAFT":
        return ctx

    sa = submit_self_assessment(provider["id"], cycle["id"], claimed=claimed,
                                documentation=documentation_for())
    ctx["self_assessment"] = sa
    if stop_at == "SELF_ASSESSMENT_SUBMITTED":
        return ctx

    ctx["self_assessment"] = verify_self_assessment(sa["id"], verified=verified)
    if stop_at == "DOCS_VERIFIED":
        ctx["cycle"] = get_success_data(api_client.get_rating_cycle(cycle["id"], ADMIN))
        return ctx

    lead = create_reliable_observer("Lead Observer One")
    ctx["lead"] = lead
    secondary = None
    if with_secondary:
        secondary = create_reliable_observer("Secondary Observer One", anchor_agreement_pct=90.00)
        ctx["secondary"] = secondary
    visit = schedule_visit(
        cycle["id"], lead["id"], window_start, window_end,
        secondary["id"] if secondary else None,
    )
    ctx["visit"] = visit
    if stop_at == "OBSERVATION_SCHEDULED":
        ctx["cycle"] = get_success_data(api_client.get_rating_cycle(cycle["id"], ADMIN))
        return ctx

    set_clock(scoring_clock if scoring_clock is not None else window_start)
    enter_six_scores(visit["id"], lead["id"], raw_score, lead_per_subscale)
    if stop_at == "SCORES_ENTERED":
        ctx["visit"] = get_success_data(api_client.get_observation_visit(visit["id"], ADMIN))
        return ctx

    if secondary:
        enter_six_scores(
            visit["id"], secondary["id"],
            secondary_raw_score if secondary_raw_score is not None else raw_score,
            secondary_per_subscale,
        )
    if stop_at == "RELIABILITY_CHECK":
        ctx["visit"] = get_success_data(api_client.get_observation_visit(visit["id"], ADMIN))
        return ctx

    ctx["visit"] = finalize_visit(visit["id"])
    if stop_at == "OBSERVATION_FINALIZED":
        ctx["cycle"] = get_success_data(api_client.get_rating_cycle(cycle["id"], ADMIN))
        return ctx

    set_clock(award_clock)
    ctx["cycle"] = award_cycle(cycle["id"], score_variant)
    if stop_at == "AWARDED":
        return ctx

    if stop_at in ("ACTIVE", "PUBLISHED"):
        # A fresh award's effective_date is the first of the following month, so the
        # cycle waits for an expiry run on or after that date.
        set_clock(activation_clock)
        run_expiry_run()
        ctx["cycle"] = get_success_data(api_client.get_rating_cycle(cycle["id"], ADMIN))
        ctx["provider"] = get_success_data(api_client.get_provider(provider["id"], ADMIN))
    if stop_at == "ACTIVE":
        return ctx

    ctx["cycle"] = publish_cycle(cycle["id"])
    ctx["provider"] = get_success_data(api_client.get_provider(provider["id"], ADMIN))
    return ctx


def setup_tier_one_active_spine(**overrides):
    """Canonical tier-1 spine: single lead observer, composite 4.00, awarded_tier 1."""
    params = {
        "stop_at": "ACTIVE",
        "claimed": points_map(learning=12, staff=8),
        "verified": points_map(learning=12, staff=8),
        "raw_score": 4.0,
    }
    params.update(overrides)
    return build_rating_spine(**params)


def setup_tier_one_published_spine(**overrides):
    params = {
        "stop_at": "PUBLISHED",
        "claimed": points_map(learning=12, staff=8),
        "verified": points_map(learning=12, staff=8),
        "raw_score": 4.0,
    }
    params.update(overrides)
    return build_rating_spine(**params)


FULL_POINTS = points_map(learning=20, staff=20, family=20, administration=20, child=20)


def setup_tier_five_spine(stop_at="ACTIVE", **overrides):
    """Two-observer spine, composite 6.00, reliability 100.00, awarded_tier 5.

    Every domain is awarded its full 20 points, so weighted_total is 100.00 and
    all three blocks clear; one VERIFIED DIRECTOR credential against an
    active_staff_fte of 1.00 puts credential_compliance_pct at 100.00.
    """
    params = {
        "stop_at": stop_at,
        "claimed": FULL_POINTS,
        "verified": FULL_POINTS,
        "raw_score": 6.0,
        "with_secondary": True,
    }
    params.update(overrides)
    return build_rating_spine(**params)


# --- Tier 4: funding, coaching and claim fixtures ---------------------------


def offer_grant(provider_id, rating_cycle_id, awarded_amount_cents=1_000_000,
                spend_deadline="2027-06-30") -> dict:
    return get_success_data(
        api_client.create_improvement_grant(
            provider_id,
            create_improvement_grant_payload(
                rating_cycle_id, awarded_amount_cents, spend_deadline
            ),
            ADMIN,
        )
    )


def accept_grant(provider_id, grant_id) -> dict:
    return get_success_data(
        api_client.grant_decision(
            grant_id, {"decision": "ACCEPT"}, make_provider_headers(provider_id)
        )
    )


def setup_open_grant(spine=None, awarded_amount_cents=1_000_000, spend_deadline="2027-06-30",
                     **spine_overrides):
    """Active published-tier provider plus one OPEN improvement grant.

    Returns (spine_ctx, grant).
    """
    ctx = spine if spine is not None else setup_tier_one_active_spine(**spine_overrides)
    grant = offer_grant(
        ctx["provider"]["id"], ctx["cycle"]["id"], awarded_amount_cents, spend_deadline
    )
    grant = accept_grant(ctx["provider"]["id"], grant["id"])
    return ctx, grant


def submit_expenditure(provider_id, grant_id, category="PROF_DEV", amount_cents=100_000,
                       invoice_date="2026-09-15", expected_grant_version=None) -> dict:
    version = expected_grant_version
    if version is None:
        version = get_success_data(api_client.get_improvement_grant(grant_id, ADMIN))["version"]
    return get_success_data(
        api_client.create_expenditure(
            grant_id,
            create_expenditure_payload(version, category, amount_cents, invoice_date),
            make_provider_headers(provider_id),
        )
    )


def adjudicate_expenditure(expenditure_id, decision="APPROVE", note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.adjudicate_expenditure(expenditure_id, payload, ADMIN)
    )


def create_allocation(provider_id, coach_user_id=COACH_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_coaching_allocation(
            provider_id, create_coaching_allocation_payload(coach_user_id, **overrides), ADMIN
        )
    )


def setup_active_allocation(spine=None, coach_user_id=COACH_USER_ID, **overrides):
    """Active provider plus one ACTIVE coaching allocation. Returns (ctx, allocation)."""
    spine_overrides = overrides.pop("spine_overrides", {})
    ctx = spine if spine is not None else setup_tier_one_active_spine(**spine_overrides)
    allocation = create_allocation(ctx["provider"]["id"], coach_user_id, **overrides)
    allocation = get_success_data(
        api_client.accept_coaching_allocation(
            allocation["id"], make_provider_headers(ctx["provider"]["id"])
        )
    )
    return ctx, allocation


def schedule_session(allocation_id, scheduled_start, scheduled_end,
                     coach_user_id=COACH_USER_ID) -> dict:
    return get_success_data(
        api_client.create_coaching_session(
            allocation_id,
            create_coaching_session_payload(scheduled_start, scheduled_end),
            make_coach_headers(coach_user_id),
        )
    )


def submit_claim(provider_id, service_month="2026-09", infant=0, toddler=0, preschool=0) -> dict:
    return get_success_data(
        api_client.create_subsidy_claim(
            provider_id,
            create_subsidy_claim_payload(service_month, infant, toddler, preschool),
            make_provider_headers(provider_id),
        )
    )


def approve_claim(claim_id, variant=None) -> dict:
    payload = {"decision": "APPROVE"}
    if variant is not None:
        payload["variant"] = variant
    return get_success_data(api_client.adjudicate_claim(claim_id, payload, ADMIN))


def pay_claim(claim_id) -> dict:
    return get_success_data(api_client.pay_claim(claim_id, ADMIN))


def setup_paid_claim(spine=None, service_month="2026-09", infant=0, toddler=10, preschool=0,
                     variant=None):
    """Published active spine plus one PAID subsidy claim. Returns (ctx, claim)."""
    ctx = spine if spine is not None else setup_tier_one_published_spine()
    claim = submit_claim(ctx["provider"]["id"], service_month, infant, toddler, preschool)
    claim = approve_claim(claim["id"], variant)
    claim = pay_claim(claim["id"])
    return ctx, claim


# --- Tier 5: remedy fixtures ------------------------------------------------


def file_appeal(provider_id, cycle_id, grounds="SCORING_ERROR",
                narrative="The composite is wrong.") -> dict:
    return get_success_data(
        api_client.create_appeal(
            cycle_id,
            {"grounds": grounds, "narrative": narrative},
            make_provider_headers(provider_id),
        )
    )


def start_appeal_review(appeal_id, reviewer_user_id="reviewer_1") -> dict:
    return get_success_data(
        api_client.appeal_review_action(
            appeal_id, {"action": "START"}, make_reviewer_headers(reviewer_user_id)
        )
    )


def setup_appeal_under_review(spine=None, grounds="SCORING_ERROR",
                              reviewer_user_id="reviewer_1"):
    """Published active cycle, appeal filed and moved to UNDER_REVIEW."""
    ctx = spine if spine is not None else setup_tier_one_published_spine()
    appeal = file_appeal(ctx["provider"]["id"], ctx["cycle"]["id"], grounds)
    appeal = start_appeal_review(appeal["id"], reviewer_user_id)
    return ctx, appeal


def file_dispute(provider_id, cycle_id, disputed_field="LICENSED_CAPACITY",
                 claimed_value="72") -> dict:
    return get_success_data(
        api_client.create_data_dispute(
            cycle_id,
            {"disputed_field": disputed_field, "claimed_value": claimed_value},
            make_provider_headers(provider_id),
        )
    )


def dispute_action(provider_or_admin_headers, dispute_id, action, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.dispute_triage_action(dispute_id, payload, provider_or_admin_headers)
    )


def setup_dispute_in_triage(spine=None, disputed_field="LICENSED_CAPACITY",
                            claimed_value="72"):
    """Published cycle plus one dispute advanced from FILED to TRIAGE."""
    ctx = spine if spine is not None else setup_tier_one_published_spine()
    dispute = file_dispute(ctx["provider"]["id"], ctx["cycle"]["id"], disputed_field, claimed_value)
    dispute = dispute_action(ADMIN, dispute["id"], "OPEN_TRIAGE")
    return ctx, dispute

