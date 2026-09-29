"""Path/body resolution (PRD §2.6) and ownership checks (PRD §2.7 step 4)."""

import store
from errors import fail

RATING_ARTIFACT = "ERR_RATING_ARTIFACT_NOT_FOUND"


def _get(collection, key, error_id, label):
    if key is None:
        fail(error_id, "%s could not be resolved" % label)
    rec = getattr(store.DB, collection).get(key)
    if rec is None:
        fail(error_id, "%s %s could not be resolved" % (label, key))
    return rec


def get_provider(provider_id):
    return _get("providers", provider_id, "ERR_PROVIDER_NOT_FOUND", "provider_id")


def get_cycle(cycle_id):
    return _get("rating_cycles", cycle_id, RATING_ARTIFACT, "rating_cycle_id")


def get_self_assessment(sa_id):
    return _get("self_assessments", sa_id, RATING_ARTIFACT, "self_assessment_id")


def get_visit(visit_id):
    return _get("observation_visits", visit_id, RATING_ARTIFACT, "observation_visit_id")


def get_score(score_id):
    return _get("observation_scores", score_id, RATING_ARTIFACT, "observation_score_id")


def get_observer(observer_id):
    return _get("observers", observer_id, "ERR_OBSERVER_NOT_FOUND", "observer_id")


def get_appeal(appeal_id):
    return _get("appeals", appeal_id, "ERR_REMEDY_NOT_FOUND", "appeal_id")


def get_dispute(dispute_id):
    return _get("data_disputes", dispute_id, "ERR_REMEDY_NOT_FOUND", "data_dispute_id")


def get_grant(grant_id):
    return _get("improvement_grants", grant_id, "ERR_FUNDING_NOT_FOUND", "improvement_grant_id")


def get_expenditure(exp_id):
    return _get("grant_expenditures", exp_id, "ERR_FUNDING_NOT_FOUND", "grant_expenditure_id")


def get_allocation(alloc_id):
    return _get("coaching_allocations", alloc_id, "ERR_FUNDING_NOT_FOUND",
                "coaching_allocation_id")


def get_session(session_id):
    return _get("coaching_sessions", session_id, "ERR_FUNDING_NOT_FOUND", "coaching_session_id")


def get_claim(claim_id):
    return _get("subsidy_claims", claim_id, "ERR_FUNDING_NOT_FOUND", "subsidy_claim_id")


def get_credential(credential_id):
    return _get("staff_credentials", credential_id, "ERR_CREDENTIAL_NOT_FOUND", "credential_id")


def get_standard_domain(domain_id):
    return _get("standard_domains", domain_id, RATING_ARTIFACT, "standard_domain_id")


# ------------------------------------------------------------------ ownership


def own_provider_id(principal, provider_id):
    """A Provider acts only on resources whose provider linkage is its own identifier."""
    if principal.role == "Provider" and principal.user_id != provider_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting provider does not own this resource")


def own_provider(principal, provider):
    own_provider_id(principal, provider["id"])


def own_cycle(principal, cycle):
    own_provider_id(principal, cycle["provider_id"])


def own_via_cycle(principal, cycle_id):
    if principal.role == "Provider":
        cycle = get_cycle(cycle_id)
        own_provider_id(principal, cycle["provider_id"])


def own_observer_on_visit(principal, visit):
    if principal.role == "Observer":
        if principal.user_id not in (visit.get("lead_observer_id"),
                                    visit.get("secondary_observer_id")):
            fail("ERR_NOT_RESOURCE_OWNER", "the acting observer is not named on this visit")


def own_coach_on_allocation(principal, allocation):
    if principal.role == "Coach":
        if principal.user_id != allocation.get("coach_user_id"):
            fail("ERR_NOT_RESOURCE_OWNER", "the acting coach is not assigned to this allocation")
