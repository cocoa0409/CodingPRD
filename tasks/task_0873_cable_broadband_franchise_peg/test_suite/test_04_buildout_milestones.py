"""Build-out density milestones: liquidated damages and the MET/MISSED boundary."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_milestone,
    TEST_USERS, make_operator_headers,
)
from test_helpers import (
    create_active_franchise, create_milestone, certify_milestone, set_clock,
    file_renewal_application,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ---- Difficulty: buildout_provisional_vs_final_damage_divergence ----
def test_interim_certify_writes_provisional_damage(api):
    """PRD 3.3: "An **interim** certification occurs when the clock is strictly
    before `deadline_date`. It keeps the milestone in `PENDING`, writes the
    computed damage into `provisional_damage_cents` (a refundable, provisional
    figure recomputed on every interim certification)".

    Design: Difficulty/dual_variant_calc/buildout_provisional_vs_final_damage_divergence
    """
    fr = create_active_franchise(api)  # homes_in_territory 10000
    ms = create_milestone(api, fr["id"], required_pct=0.60, deadline_date="2026-08-01")
    # Clock at startup default 2026-05-01 < deadline -> interim; homes_passed 5000.
    data = certify_milestone(api, fr["id"], ms["id"], homes_passed=5000)
    assert_milestone(data)
    # shortfall (6000 - 5000) * 2500 = 2500000.
    assert data["provisional_damage_cents"] == 2500000
    assert data["status"] == "PENDING"


def test_final_certify_writes_final_damage_diverges(api):
    """PRD 3.3: "If it falls short, the milestone becomes `MISSED` and
    `final_damage_cents` is set to the computed shortfall damage — a
    non-refundable figure."
    PRD 3.3: "The `provisional_damage_cents` from the last interim certification
    is retained rather than cleared, so both the provisional and final figures
    remain observable on the terminal milestone."

    Design: Difficulty/dual_variant_calc/buildout_provisional_vs_final_damage_divergence
    """
    fr = create_active_franchise(api)
    ms = create_milestone(api, fr["id"], required_pct=0.60, deadline_date="2026-08-01")
    certify_milestone(api, fr["id"], ms["id"], homes_passed=5000)  # interim -> provisional 2500000
    set_clock(api, "2026-08-15T00:00:00Z")  # at/after deadline -> final
    data = certify_milestone(api, fr["id"], ms["id"], homes_passed=5800)
    # 5800/10000 = 0.58 < 0.60 -> MISSED; shortfall (6000-5800)*2500 = 500000.
    assert data["status"] == "MISSED"
    assert data["final_damage_cents"] == 500000
    assert data["provisional_damage_cents"] == 2500000


# ---- Difficulty: buildout_met_at_exact_required_pct ----
def test_certify_exact_required_pct_marks_met(api):
    """PRD 3.3: "Whether the milestone is met is decided by comparing the fraction
    of homes passed — `homes_passed` divided by the franchise's
    `homes_in_territory` — against `required_pct`, with the boundary inclusive:
    the milestone is met when the fraction passed is at least `required_pct`."

    Design: Difficulty/boundary_precision_check/buildout_met_at_exact_required_pct
    """
    fr = create_active_franchise(api)
    ms = create_milestone(api, fr["id"], required_pct=0.60, deadline_date="2026-08-01")
    set_clock(api, "2026-08-15T00:00:00Z")  # final certify
    data = certify_milestone(api, fr["id"], ms["id"], homes_passed=6000)  # 6000/10000 == 0.60
    assert data["status"] == "MET"


def test_met_milestone_final_damage_zero(api):
    """PRD 3.3: "If the fraction passed meets `required_pct`, the milestone
    becomes `MET` and `final_damage_cents` is set to 0."

    Design: Difficulty/boundary_precision_check/buildout_met_at_exact_required_pct
    """
    fr = create_active_franchise(api)
    ms = create_milestone(api, fr["id"], required_pct=0.60, deadline_date="2026-08-01")
    set_clock(api, "2026-08-15T00:00:00Z")
    data = certify_milestone(api, fr["id"], ms["id"], homes_passed=6000)
    assert data["status"] == "MET"
    assert data["final_damage_cents"] == 0


# ---- Difficulty: renewal_approve_requires_milestones_met ----
def test_renewal_approve_pending_milestone_returns_milestones_not_met(api):
    """PRD 3.8: "For a `RENEWAL` approval there is a further cross-entity
    precondition, evaluated after the compliance check: every build-out milestone
    of the franchise must be in `MET`; if any milestone is not met, the approval
    is rejected with `ERR_MILESTONES_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/renewal_approve_requires_milestones_met
    """
    fr = create_active_franchise(api)
    create_milestone(api, fr["id"], required_pct=0.60, deadline_date="2026-08-01")  # PENDING
    app = file_renewal_application(api, fr["id"], proposed_term_end_date="2040-01-01")
    resp = api.decide_application(app["id"], {"decision": "APPROVE"}, AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_MILESTONES_NOT_MET.value, 409)


def test_renewal_stays_submitted_after_blocked_approve(api):
    """PRD 3.8: "every build-out milestone of the franchise must be in `MET`; if
    any milestone is not met, the approval is rejected with
    `ERR_MILESTONES_NOT_MET`."
    PRD 3.8: "Approval is defined only from `SUBMITTED`".

    Design: Difficulty/cross_entity_state_dependency/renewal_approve_requires_milestones_met
    """
    fr = create_active_franchise(api)
    create_milestone(api, fr["id"], required_pct=0.60, deadline_date="2026-08-01")
    app = file_renewal_application(api, fr["id"], proposed_term_end_date="2040-01-01")
    api.decide_application(app["id"], {"decision": "APPROVE"}, AUTHORITY)
    after = validate_success(api.get_application(app["id"], AUTHORITY), 200)
    assert after["status"] == "SUBMITTED"
