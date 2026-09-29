"""Composite state builders.

Every test starts against an empty database, so all preconditions are built
from scratch through the public API. The builders below are layered:

* tier 1 — single-step helpers (clock, one create, one transition)
* tier 2 — entity hierarchy shortcuts (an ACTIVE agreement, an ACTIVE
  physician, an assigned enrollee, an open risk pool)
* tier 3 — full-lifecycle shortcuts (a POSTED enrollment file, a PAID claim,
  a FINAL scorecard, a RESERVED pool)
* tier 4 — accumulation targeting (a pool driven to a chosen funded/paid
  position, an enrollee driven past the stop-loss attachment)
* tier 5 — the two reusable multi-entity scenarios the money examples in the
  PRD are written against
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import IpaApiClient
from .factories import (
    agreement_payload,
    assignment_payload,
    claim_payload,
    enrollee_payload,
    enrollment_file_payload,
    enrollment_row_payload,
    physician_payload,
    risk_pool_payload,
    scorecard_payload,
    state_payload,
)
from .test_users import (
    CLAIMS_EXAMINER_HEADERS,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    make_payer_representative_headers,
)

Json = Dict[str, Any]


# ===========================================================================
# Tier 1 — single-step helpers
# ===========================================================================


def set_clock(api: IpaApiClient, instant: str, headers: Optional[Json] = None) -> Json:
    """Move the logical clock and return the response data."""
    response = api.set_clock(instant, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def create_agreement(api: IpaApiClient, **overrides: Any) -> Json:
    response = api.create_agreement(agreement_payload(**overrides), IPA_ADMIN_HEADERS)
    return validate_success(response, 201)


def activate_agreement(api: IpaApiClient, agreement_id: str) -> Json:
    response = api.set_agreement_state(
        agreement_id, state_payload("ACTIVE"), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def read_agreement(api: IpaApiClient, agreement_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_agreement(agreement_id, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def read_physician(api: IpaApiClient, physician_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_physician(physician_id, headers or NETWORK_MANAGER_HEADERS)
    return validate_success(response, 200)


def read_enrollee(api: IpaApiClient, enrollee_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_enrollee(enrollee_id, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def read_assignment(api: IpaApiClient, assignment_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_assignment(assignment_id, headers or NETWORK_MANAGER_HEADERS)
    return validate_success(response, 200)


def read_file(api: IpaApiClient, file_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_enrollment_file(file_id, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def read_remittance(api: IpaApiClient, remittance_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_remittance(remittance_id, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def read_pool(api: IpaApiClient, pool_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_risk_pool(pool_id, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def read_claim(api: IpaApiClient, claim_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_claim(claim_id, headers or CLAIMS_EXAMINER_HEADERS)
    return validate_success(response, 200)


def read_recovery(api: IpaApiClient, recovery_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_recovery(recovery_id, headers or CLAIMS_EXAMINER_HEADERS)
    return validate_success(response, 200)


def read_scorecard(api: IpaApiClient, scorecard_id: str, headers: Optional[Json] = None) -> Json:
    response = api.get_scorecard(scorecard_id, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def read_distribution(
    api: IpaApiClient, distribution_id: str, headers: Optional[Json] = None
) -> Json:
    response = api.get_distribution(distribution_id, headers or IPA_ADMIN_HEADERS)
    return validate_success(response, 200)


def enrollee_version(api: IpaApiClient, enrollee_id: str) -> int:
    return read_enrollee(api, enrollee_id)["version"]


def physician_version(api: IpaApiClient, physician_id: str) -> int:
    return read_physician(api, physician_id)["version"]


# ===========================================================================
# Tier 2 — entity hierarchy shortcuts
# ===========================================================================


def create_active_agreement(api: IpaApiClient, **overrides: Any) -> Json:
    """Create an agreement and drive it DRAFT to ACTIVE."""
    agreement = create_agreement(api, **overrides)
    activate_agreement(api, agreement["id"])
    return read_agreement(api, agreement["id"])


def create_physician(api: IpaApiClient, agreement_id: str, **overrides: Any) -> Json:
    response = api.create_physician(
        agreement_id, physician_payload(**overrides), NETWORK_MANAGER_HEADERS
    )
    return validate_success(response, 201)


def credential_physician(api: IpaApiClient, physician_id: str) -> Json:
    response = api.set_physician_state(
        physician_id, state_payload("CREDENTIALED"), NETWORK_MANAGER_HEADERS
    )
    return validate_success(response, 200)


def activate_physician(api: IpaApiClient, physician_id: str) -> Json:
    response = api.set_physician_state(
        physician_id, state_payload("ACTIVE"), NETWORK_MANAGER_HEADERS
    )
    return validate_success(response, 200)


def create_active_physician(api: IpaApiClient, agreement_id: str, **overrides: Any) -> Json:
    """Create a physician and walk APPLICANT to CREDENTIALED to ACTIVE."""
    physician = create_physician(api, agreement_id, **overrides)
    credential_physician(api, physician["id"])
    activate_physician(api, physician["id"])
    return read_physician(api, physician["id"])


def give_exit_notice(api: IpaApiClient, physician_id: str, headers: Optional[Json] = None) -> Json:
    response = api.set_physician_state(
        physician_id, state_payload("NOTICE_GIVEN"), headers or NETWORK_MANAGER_HEADERS
    )
    return validate_success(response, 200)


def create_enrollee(api: IpaApiClient, agreement_id: str, **overrides: Any) -> Json:
    response = api.create_enrollee(
        agreement_id, enrollee_payload(**overrides), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 201)


def assign_enrollee(
    api: IpaApiClient,
    enrollee_id: str,
    physician_id: str,
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Place a member on a panel, reading the enrollee's current version first."""
    payload = assignment_payload(
        enrollee_id, physician_id, enrollee_version(api, enrollee_id), **overrides
    )
    response = api.create_assignment(payload, headers or NETWORK_MANAGER_HEADERS)
    return validate_success(response, 201)


def terminate_assignment(api: IpaApiClient, assignment_id: str) -> Json:
    response = api.set_assignment_state(
        assignment_id, state_payload("TERMINATED"), NETWORK_MANAGER_HEADERS
    )
    return validate_success(response, 200)


def create_pool(api: IpaApiClient, agreement_id: str, **overrides: Any) -> Json:
    response = api.create_risk_pool(
        agreement_id, risk_pool_payload(**overrides), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 201)


def create_calendar_2026_pools(api: IpaApiClient, agreement_id: str) -> Dict[str, Json]:
    """One PROFESSIONAL and one INSTITUTIONAL pool covering all of 2026."""
    return {
        "PROFESSIONAL": create_pool(api, agreement_id, pool_type="PROFESSIONAL"),
        "INSTITUTIONAL": create_pool(api, agreement_id, pool_type="INSTITUTIONAL"),
    }


# ===========================================================================
# Tier 3 — full-lifecycle shortcuts
# ===========================================================================


def create_enrollment_file(api: IpaApiClient, agreement_id: str, **overrides: Any) -> Json:
    response = api.create_enrollment_file(
        agreement_id, enrollment_file_payload(**overrides), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 201)


def append_row(
    api: IpaApiClient,
    file_id: str,
    external_member_id: str,
    physician_npi: str,
    **overrides: Any,
) -> Json:
    response = api.create_enrollment_file_row(
        file_id,
        enrollment_row_payload(external_member_id, physician_npi, **overrides),
        IPA_ADMIN_HEADERS,
    )
    return validate_success(response, 201)


def parse_file(api: IpaApiClient, file_id: str, headers: Optional[Json] = None) -> Json:
    response = api.set_enrollment_file_state(
        file_id, state_payload("PARSED"), headers or IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def reconcile_file(api: IpaApiClient, file_id: str) -> Json:
    response = api.set_enrollment_file_state(
        file_id, state_payload("RECONCILED"), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def post_file(api: IpaApiClient, file_id: str) -> Json:
    response = api.set_enrollment_file_state(
        file_id, state_payload("POSTED"), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def dispute_file(
    api: IpaApiClient, file_id: str, agreement_id: str, dispute_reason: str
) -> Json:
    response = api.set_enrollment_file_state(
        file_id,
        state_payload("DISPUTED", dispute_reason=dispute_reason),
        make_payer_representative_headers(agreement_id),
    )
    return validate_success(response, 200)


def list_file_remittances(api: IpaApiClient, file_id: str, **params: Any) -> List[Json]:
    query = {"limit": 10, "offset": 0}
    query.update(params)
    response = api.list_file_remittances(file_id, IPA_ADMIN_HEADERS, query)
    rows, _meta = validate_paginated(response)
    return rows


def sole_remittance(api: IpaApiClient, file_id: str) -> Json:
    rows = list_file_remittances(api, file_id)
    assert rows, f"no remittance was created for file {file_id}"
    return rows[0]


def build_reconciled_file(
    api: IpaApiClient,
    agreement_id: str,
    rows: Sequence[Dict[str, Any]],
    coverage_month: str = "2026-07",
    **file_overrides: Any,
) -> Dict[str, Any]:
    """Open a file, append rows, PARSE it and RECONCILE it.

    ``rows`` is a sequence of kwargs dicts for ``append_row``, each carrying at
    least ``external_member_id`` and ``physician_npi``.
    """
    enrollment_file = create_enrollment_file(
        api, agreement_id, coverage_month=coverage_month, **file_overrides
    )
    for row in rows:
        append_row(api, enrollment_file["id"], **row)
    parse_file(api, enrollment_file["id"])
    reconcile_file(api, enrollment_file["id"])
    return {
        "file": read_file(api, enrollment_file["id"]),
        "remittance": sole_remittance(api, enrollment_file["id"]),
    }


def build_posted_file(
    api: IpaApiClient,
    agreement_id: str,
    rows: Sequence[Dict[str, Any]],
    coverage_month: str = "2026-07",
    **file_overrides: Any,
) -> Dict[str, Any]:
    """Drive a file all the way to POSTED so the pool ledgers are funded."""
    built = build_reconciled_file(
        api, agreement_id, rows, coverage_month=coverage_month, **file_overrides
    )
    post_file(api, built["file"]["id"])
    return {
        "file": read_file(api, built["file"]["id"]),
        "remittance": read_remittance(api, built["remittance"]["id"]),
    }


def create_claim(
    api: IpaApiClient,
    agreement_id: str,
    enrollee_id: str,
    physician_id: str,
    **overrides: Any,
) -> Json:
    response = api.create_claim(
        claim_payload(agreement_id, enrollee_id, physician_id, **overrides),
        CLAIMS_EXAMINER_HEADERS,
    )
    return validate_success(response, 201)


def approve_claim(api: IpaApiClient, claim_id: str, allowed_cents: int) -> Json:
    response = api.set_claim_state(
        claim_id,
        state_payload("ADJUDICATED_APPROVED", allowed_cents=allowed_cents),
        CLAIMS_EXAMINER_HEADERS,
    )
    return validate_success(response, 200)


def deny_claim(api: IpaApiClient, claim_id: str, denial_reason: str) -> Json:
    response = api.set_claim_state(
        claim_id,
        state_payload("ADJUDICATED_DENIED", denial_reason=denial_reason),
        CLAIMS_EXAMINER_HEADERS,
    )
    return validate_success(response, 200)


def pay_claim_state(api: IpaApiClient, claim_id: str) -> Json:
    response = api.set_claim_state(
        claim_id, state_payload("PAID"), CLAIMS_EXAMINER_HEADERS
    )
    return validate_success(response, 200)


def build_paid_claim(
    api: IpaApiClient,
    agreement_id: str,
    enrollee_id: str,
    physician_id: str,
    amount_cents: int,
    **overrides: Any,
) -> Json:
    """Intake, approve and pay one claim for ``amount_cents``."""
    claim = create_claim(
        api,
        agreement_id,
        enrollee_id,
        physician_id,
        billed_cents=amount_cents,
        **overrides,
    )
    approve_claim(api, claim["id"], amount_cents)
    pay_claim_state(api, claim["id"])
    return read_claim(api, claim["id"])


def build_approved_claim(
    api: IpaApiClient,
    agreement_id: str,
    enrollee_id: str,
    physician_id: str,
    amount_cents: int,
    **overrides: Any,
) -> Json:
    """Intake and approve one claim, leaving it unpaid."""
    claim = create_claim(
        api,
        agreement_id,
        enrollee_id,
        physician_id,
        billed_cents=amount_cents,
        **overrides,
    )
    approve_claim(api, claim["id"], amount_cents)
    return read_claim(api, claim["id"])


def create_scorecard(api: IpaApiClient, physician_id: str, **overrides: Any) -> Json:
    payload = scorecard_payload(
        physician_id, physician_version(api, physician_id), **overrides
    )
    response = api.create_scorecard(payload, IPA_ADMIN_HEADERS)
    return validate_success(response, 201)


def finalize_scorecard(api: IpaApiClient, scorecard_id: str) -> Json:
    response = api.set_scorecard_state(
        scorecard_id, state_payload("FINAL"), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def build_final_scorecard(api: IpaApiClient, physician_id: str, **overrides: Any) -> Json:
    """Record a scorecard and finalise it."""
    scorecard = create_scorecard(api, physician_id, **overrides)
    finalize_scorecard(api, scorecard["id"])
    return read_scorecard(api, scorecard["id"])


def close_incurral(api: IpaApiClient, pool_id: str) -> Json:
    response = api.set_risk_pool_state(
        pool_id, state_payload("CLOSED_FOR_INCURRAL"), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def reserve_pool(api: IpaApiClient, pool_id: str, **overrides: Any) -> Json:
    response = api.set_risk_pool_state(
        pool_id, state_payload("RESERVED", **overrides), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def propose_settlement(api: IpaApiClient, pool_id: str) -> Json:
    response = api.set_risk_pool_state(
        pool_id, state_payload("SETTLEMENT_PROPOSED"), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def settle_pool(api: IpaApiClient, pool_id: str) -> Json:
    response = api.set_risk_pool_state(
        pool_id, state_payload("SETTLED"), IPA_ADMIN_HEADERS
    )
    return validate_success(response, 200)


def list_pool_distributions(api: IpaApiClient, pool_id: str, **params: Any) -> List[Json]:
    query = {"pool_id": pool_id, "limit": 10, "offset": 0}
    query.update(params)
    response = api.list_distributions(IPA_ADMIN_HEADERS, query)
    rows, _meta = validate_paginated(response)
    return rows


def create_recovery(api: IpaApiClient, pool_id: str, enrollee_id: str, headers=None) -> Json:
    response = api.create_recovery(
        {"pool_id": pool_id, "enrollee_id": enrollee_id},
        headers or CLAIMS_EXAMINER_HEADERS,
    )
    return validate_success(response, 201)


def submit_recovery(api: IpaApiClient, recovery_id: str, headers=None) -> Json:
    response = api.set_recovery_state(
        recovery_id, state_payload("SUBMITTED"), headers or CLAIMS_EXAMINER_HEADERS
    )
    return validate_success(response, 200)


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================


def build_single_member_funded_pool(
    api: IpaApiClient,
    base_pmpm_cents: int = 20000,
    coverage_month: str = "2026-07",
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """One member, one PROFESSIONAL pool, one POSTED coverage month.

    With ``quality_withhold_bps`` 0 and the whole net payable routed to the
    professional pool, the pool's ``funded_cents`` lands exactly on the single
    member's ``gross_pmpm_cents`` and ``member_months_bps`` on 10000.
    """
    overrides: Dict[str, Any] = {
        "base_pmpm_cents": base_pmpm_cents,
        "reconciliation_method": "MEMBER_MONTHS_PRORATED",
        "professional_pool_share_bps": 10000,
        "institutional_pool_share_bps": 0,
        "quality_withhold_bps": 0,
    }
    overrides.update(agreement_overrides)

    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, **overrides)
    physician = create_active_physician(api, agreement["id"])
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    enrollee = create_enrollee(api, agreement["id"], risk_score_bps=10000)
    assign_enrollee(api, enrollee["id"], physician["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    posted = build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": enrollee["external_member_id"],
                "physician_npi": physician["npi"],
                "claimed_capitation_cents": base_pmpm_cents,
            }
        ],
        coverage_month=coverage_month,
    )
    return {
        "agreement": read_agreement(api, agreement["id"]),
        "physician": read_physician(api, physician["id"]),
        "enrollee": read_enrollee(api, enrollee["id"]),
        "pool": read_pool(api, pool["id"]),
        "file": posted["file"],
        "remittance": posted["remittance"],
    }


def build_enrollee_past_attachment(
    api: IpaApiClient, attachment_cents: int, overshoot_cents: int = 1
) -> Dict[str, Any]:
    """Drive one member's paid total to ``attachment_cents + overshoot_cents``."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        stop_loss_attachment_cents=attachment_cents,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
    )
    physician = create_active_physician(api, agreement["id"])
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    enrollee = create_enrollee(api, agreement["id"], risk_score_bps=10000)
    assign_enrollee(api, enrollee["id"], physician["id"])

    build_paid_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        attachment_cents,
        service_date="2026-04-10T00:00:00Z",
    )
    if overshoot_cents:
        build_paid_claim(
            api,
            agreement["id"],
            enrollee["id"],
            physician["id"],
            overshoot_cents,
            service_date="2026-04-11T00:00:00Z",
        )
    return {
        "agreement": read_agreement(api, agreement["id"]),
        "physician": read_physician(api, physician["id"]),
        "enrollee": read_enrollee(api, enrollee["id"]),
        "pool": read_pool(api, pool["id"]),
    }


# ===========================================================================
# Tier 5 — the two reusable scenarios the PRD money examples describe
# ===========================================================================


def build_reserving_scenario(api: IpaApiClient) -> Dict[str, Any]:
    """A pool at ``funded_cents`` 20000, ``paid_claims_cents`` 13520, 10000 bps.

    This is the pool position the PRD uses to contrast the two reserving
    conventions: 3380 cents under ``COMPLETION_FACTOR`` against 1480 cents
    under ``PMPM_LOSS_RATIO``. The pool is left in ``CLOSED_FOR_INCURRAL`` with
    the logical clock at 2027-01-01T00:00:00Z.
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Cascade Health Plan",
        base_pmpm_cents=20000,
        reconciliation_method="MEMBER_MONTHS_PRORATED",
        ibnr_method="COMPLETION_FACTOR",
        ibnr_completion_factor_bps=8000,
        target_claims_pmpm_cents=15000,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
    )
    physician = create_active_physician(api, agreement["id"], full_name="Ivy Chen")
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    enrollee = create_enrollee(api, agreement["id"], risk_score_bps=10000)
    assign_enrollee(api, enrollee["id"], physician["id"])

    claim = build_paid_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        13520,
        downstream_provider_name="Rainier Imaging",
        service_date="2026-06-15T00:00:00Z",
    )

    set_clock(api, "2026-08-01T00:00:00Z")
    posted = build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": enrollee["external_member_id"],
                "physician_npi": physician["npi"],
                "claimed_capitation_cents": 20000,
            }
        ],
    )

    set_clock(api, "2027-01-01T00:00:00Z")
    close_incurral(api, pool["id"])
    return {
        "agreement": read_agreement(api, agreement["id"]),
        "physician": read_physician(api, physician["id"]),
        "enrollee": read_enrollee(api, enrollee["id"]),
        "pool": read_pool(api, pool["id"]),
        "claim": claim,
        "file": posted["file"],
        "remittance": posted["remittance"],
    }


# The three-member July roster the reconciliation examples are written against.
PRORATED_ROSTER_MEMBER_IDS = ("R-0001", "R-0002", "R-0003")


def build_prorated_july_roster(
    api: IpaApiClient,
    with_pools: bool = False,
    stop_at: str = "RECONCILED",
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """The three-member 2026-07 roster the reconciliation example describes.

    An ``ADULT`` member on ``HMO`` with ``gross_pmpm_cents`` 37500 covered for
    all 31 days, a ``SENIOR`` member on ``HMO_PLUS`` with ``gross_pmpm_cents``
    89500 whose assignment starts on 16 July, and a ``PEDIATRIC`` member on
    ``HMO`` with ``gross_pmpm_cents`` 8000 whose assignment is terminated on 11
    July after 10 covered days.

    ``stop_at`` selects how far the enrollment file is driven: ``"PARSED"``,
    ``"RECONCILED"`` (the default) or ``"POSTED"``.
    """
    overrides: Dict[str, Any] = {
        "base_pmpm_cents": 30000,
        "reconciliation_method": "MEMBER_MONTHS_PRORATED",
        "quality_withhold_bps": 700,
        "professional_pool_share_bps": 6000,
        "institutional_pool_share_bps": 4000,
        "max_panel_size": 10,
    }
    overrides.update(agreement_overrides)

    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, **overrides)
    physician = create_active_physician(api, agreement["id"])

    pools: Dict[str, Json] = {}
    if with_pools:
        pools = create_calendar_2026_pools(api, agreement["id"])

    first = create_enrollee(
        api,
        agreement["id"],
        external_member_id=PRORATED_ROSTER_MEMBER_IDS[0],
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=12500,
    )
    assign_enrollee(api, first["id"], physician["id"])

    second = create_enrollee(
        api,
        agreement["id"],
        external_member_id=PRORATED_ROSTER_MEMBER_IDS[1],
        age_band="SENIOR",
        benefit_tier="HMO_PLUS",
        risk_score_bps=20000,
    )
    assign_enrollee(
        api, second["id"], physician["id"], effective_date="2026-07-16T00:00:00Z"
    )

    third = create_enrollee(
        api,
        agreement["id"],
        external_member_id=PRORATED_ROSTER_MEMBER_IDS[2],
        age_band="PEDIATRIC",
        benefit_tier="HMO",
        risk_score_bps=3000,
    )
    third_assignment = assign_enrollee(api, third["id"], physician["id"])

    set_clock(api, "2026-07-11T00:00:00Z", NETWORK_MANAGER_HEADERS)
    terminate_assignment(api, third_assignment["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    enrollment_file = create_enrollment_file(api, agreement["id"], coverage_month="2026-07")
    append_row(
        api,
        enrollment_file["id"],
        PRORATED_ROSTER_MEMBER_IDS[0],
        physician["npi"],
        row_action="ADD",
        claimed_capitation_cents=37500,
        effective_date="2026-07-01T00:00:00Z",
    )
    append_row(
        api,
        enrollment_file["id"],
        PRORATED_ROSTER_MEMBER_IDS[1],
        physician["npi"],
        row_action="ADD",
        claimed_capitation_cents=40000,
        effective_date="2026-07-16T00:00:00Z",
    )
    append_row(
        api,
        enrollment_file["id"],
        PRORATED_ROSTER_MEMBER_IDS[2],
        physician["npi"],
        row_action="TERM",
        claimed_capitation_cents=2581,
        effective_date="2026-07-11T00:00:00Z",
    )
    parse_file(api, enrollment_file["id"])

    remittance: Optional[Json] = None
    if stop_at in ("RECONCILED", "POSTED"):
        reconcile_file(api, enrollment_file["id"])
        remittance = sole_remittance(api, enrollment_file["id"])
    if stop_at == "POSTED":
        post_file(api, enrollment_file["id"])
        remittance = read_remittance(api, remittance["id"])

    result: Dict[str, Any] = {
        "agreement": read_agreement(api, agreement["id"]),
        "physician": read_physician(api, physician["id"]),
        "enrollees": [
            read_enrollee(api, first["id"]),
            read_enrollee(api, second["id"]),
            read_enrollee(api, third["id"]),
        ],
        "third_assignment": read_assignment(api, third_assignment["id"]),
        "file": read_file(api, enrollment_file["id"]),
        "remittance": remittance,
    }
    if with_pools:
        result["pools"] = {
            pool_type: read_pool(api, pool["id"]) for pool_type, pool in pools.items()
        }
    return result


def lenient_data(response) -> Json:
    """Read ``data`` from a response without asserting on its status.

    Used only where a builder needs to look at a body it has already asserted
    on by other means.
    """
    return get_success_data(response)
