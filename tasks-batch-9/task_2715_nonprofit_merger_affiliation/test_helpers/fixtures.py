"""Composite setup helpers.

The harness restarts the server before every test, so each test starts from an
empty registry and every precondition has to be built through the API. These
helpers walk the deal lifecycle one declared transition at a time and return a
mutable context dict:

    ctx = {
        "org_a": {...},          # initiator organization row
        "org_b": {...},          # target organization row
        "deal": {...},           # latest restructuring row read back
        "loi": {...},            # governing letter of intent, when one exists
        "approval_initiator": {...},
        "approval_target": {...},
        "filing": {...},
    }

Ownership-gated calls are threaded with the acting organization's own id,
because a StrategyOfficer and a BoardSecretary authenticate as the party
Organization itself.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)

Json = Dict[str, Any]

ORG_A = {
    "legal_name": "Riverside Youth Alliance",
    "ein": "11-1111111",
    "state_code": "CA",
    "mission_code": "YM-YOUTH_MENTORING",
    "annual_expense_cents": 100000002,
    "unrestricted_net_assets_cents": 59916670,
}
ORG_B = {
    "legal_name": "Harbor Youth Collective",
    "ein": "22-2222222",
    "state_code": "CA",
    "mission_code": "YM-YOUTH_MENTORING",
    "annual_expense_cents": 100000002,
    "unrestricted_net_assets_cents": 40000000,
}
ORG_C = {
    "legal_name": "Delta Youth Partners",
    "ein": "55-5555555",
    "state_code": "CA",
    "mission_code": "YM-YOUTH_MENTORING",
    "annual_expense_cents": 100000002,
    "unrestricted_net_assets_cents": 40000000,
}


# ----------------------------------------------------------------------
# Primitive builders
# ----------------------------------------------------------------------
def create_organization(api: ApiClient, spec: Optional[Json] = None, **overrides: Any) -> Json:
    payload = dict(spec) if spec else f.organization_payload()
    payload.update(overrides)
    return validate_success(api.create_organization(payload, PLATFORM_ADMIN), 201)


def read_deal(api: ApiClient, deal_id: str, headers: Optional[Json] = None) -> Json:
    return validate_success(api.get_restructuring(deal_id, headers or PLATFORM_ADMIN))


def deal_version(api: ApiClient, deal_id: str, headers: Optional[Json] = None) -> int:
    return read_deal(api, deal_id, headers)["version"]


def create_program(api: ApiClient, org_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_program(f.program_payload(org_id, **overrides), PLATFORM_ADMIN), 201
    )


def create_fund(api: ApiClient, org_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_restricted_fund(f.restricted_fund_payload(org_id, **overrides), TRUST_COUNSEL),
        201,
    )


def set_clock(api: ApiClient, current_utc: str) -> Json:
    return validate_success(api.set_clock(f.clock_payload(current_utc), PLATFORM_ADMIN))


def run_sweep(api: ApiClient) -> Json:
    return validate_success(api.run_regulatory_sweep({}, PLATFORM_ADMIN))


# ----------------------------------------------------------------------
# Lifecycle stages
# ----------------------------------------------------------------------
def setup_two_orgs(api: ApiClient) -> Json:
    """Register the initiator and the target organizations."""
    org_a = create_organization(api, ORG_A)
    org_b = create_organization(api, ORG_B)
    return {"org_a": org_a, "org_b": org_b}


def setup_deal_exploratory(api: ApiClient, ctx: Optional[Json] = None, **overrides: Any) -> Json:
    """Open the confidential exploratory conversation. Deal lands EXPLORATORY."""
    ctx = {} if ctx is None else ctx
    if "org_a" not in ctx:
        ctx.update(setup_two_orgs(api))
    payload = f.restructuring_payload(ctx["org_a"]["id"], ctx["org_b"]["id"], **overrides)
    ctx["deal"] = validate_success(
        api.create_restructuring(payload, make_strategy_officer_headers(ctx["org_a"]["id"])), 201
    )
    return ctx


def setup_deal_rationale_built(api: ApiClient, ctx: Optional[Json] = None, **overrides: Any) -> Json:
    """First SCREENING snapshot advances the deal EXPLORATORY -> RATIONALE_BUILT."""
    ctx = {} if ctx is None else ctx
    if "deal" not in ctx:
        ctx = setup_deal_exploratory(api, ctx)
    deal_id = ctx["deal"]["id"]
    ctx["screening"] = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "SCREENING", **overrides),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )
    ctx["deal"] = read_deal(api, deal_id)
    return ctx


def setup_deal_loi_negotiation(api: ApiClient, ctx: Optional[Json] = None, **overrides: Any) -> Json:
    """Issue the round's letter of intent. Deal advances RATIONALE_BUILT -> LOI_NEGOTIATION."""
    ctx = {} if ctx is None else ctx
    if "screening" not in ctx:
        ctx = setup_deal_rationale_built(api, ctx)
    deal_id = ctx["deal"]["id"]
    version = deal_version(api, deal_id)
    payload = f.letter_of_intent_payload(deal_id, version, **overrides)
    ctx["loi"] = validate_success(
        api.create_letter_of_intent(payload, make_strategy_officer_headers(ctx["org_a"]["id"])), 201
    )
    ctx["deal"] = read_deal(api, deal_id)
    return ctx


def setup_deal_diligence(api: ApiClient, ctx: Optional[Json] = None) -> Json:
    """The target countersigns. Deal advances LOI_NEGOTIATION -> DILIGENCE."""
    ctx = {} if ctx is None else ctx
    if "loi" not in ctx:
        ctx = setup_deal_loi_negotiation(api, ctx)
    ctx["loi"] = validate_success(
        api.execute_letter_of_intent(
            ctx["loi"]["id"], f.execute_payload(), make_strategy_officer_headers(ctx["org_b"]["id"])
        )
    )
    ctx["deal"] = read_deal(api, ctx["deal"]["id"])
    return ctx


def setup_deal_diligence_closed(api: ApiClient, ctx: Optional[Json] = None) -> Json:
    """Raise a finding, snapshot the diligence-adjusted variant, respond and clear.

    Clearing the only finding satisfies the aggregate closure condition, so the
    deal advances DILIGENCE -> DILIGENCE_CLOSED. The diligence-adjusted snapshot
    is deliberately taken while the finding is still open, so its
    open_diligence_exposure_cents is non-zero.
    """
    ctx = {} if ctx is None else ctx
    if ctx.get("loi", {}).get("status") != "EXECUTED":
        ctx = setup_deal_diligence(api, ctx)
    deal_id = ctx["deal"]["id"]
    ctx["finding"] = validate_success(
        api.create_diligence_request(f.diligence_request_payload(deal_id), DILIGENCE_LEAD), 201
    )
    ctx["adjusted"] = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "DILIGENCE_ADJUSTED"),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )
    validate_success(
        api.respond_diligence_request(
            ctx["finding"]["id"],
            f.diligence_respond_payload(),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        )
    )
    ctx["finding"] = validate_success(
        api.clear_diligence_request(
            ctx["finding"]["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2
        )
    )
    ctx["deal"] = read_deal(api, deal_id)
    return ctx


def setup_deal_structure_selected(
    api: ApiClient, ctx: Optional[Json] = None, **overrides: Any
) -> Json:
    """Commit the deal to its structure. Deal advances DILIGENCE_CLOSED -> STRUCTURE_SELECTED."""
    ctx = {} if ctx is None else ctx
    if "finding" not in ctx:
        ctx = setup_deal_diligence_closed(api, ctx)
    deal_id = ctx["deal"]["id"]
    ctx["deal"] = validate_success(
        api.select_structure(
            deal_id,
            f.select_structure_payload(**overrides),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        )
    )
    return ctx


def setup_deal_board_approval(api: ApiClient, ctx: Optional[Json] = None) -> Json:
    """Record both boards' resolutions. Deal advances STRUCTURE_SELECTED -> BOARD_APPROVAL.

    Each request carries its own freshly read deal version, because the pin is
    evaluated per request rather than per side effect.
    """
    ctx = {} if ctx is None else ctx
    if ctx.get("deal", {}).get("status") != "STRUCTURE_SELECTED":
        ctx = setup_deal_structure_selected(api, ctx)
    deal_id = ctx["deal"]["id"]

    ctx["approval_initiator"] = validate_success(
        api.create_board_approval(
            f.board_approval_payload(deal_id, deal_version(api, deal_id), "INITIATOR"),
            make_board_secretary_headers(ctx["org_a"]["id"]),
        ),
        201,
    )
    ctx["approval_target"] = validate_success(
        api.create_board_approval(
            f.board_approval_payload(
                deal_id,
                deal_version(api, deal_id),
                "TARGET",
                seats_total=12,
                recusals=0,
                votes_for=8,
                votes_against=4,
                abstentions=0,
                conflict_disclosures_count=0,
                recording_secretary_ref="SEC-B-1",
            ),
            make_board_secretary_headers(ctx["org_b"]["id"]),
        ),
        201,
    )
    ctx["deal"] = read_deal(api, deal_id)
    return ctx


def setup_deal_regulatory_review(api: ApiClient, ctx: Optional[Json] = None) -> Json:
    """Certify both resolutions. Once both parties hold a CERTIFIED resolution the
    deal advances BOARD_APPROVAL -> REGULATORY_REVIEW; a deal whose
    ag_review_required is false continues straight on to INTEGRATION."""
    ctx = {} if ctx is None else ctx
    if "approval_initiator" not in ctx:
        ctx = setup_deal_board_approval(api, ctx)
    ctx["approval_initiator"] = validate_success(
        api.certify_board_approval(
            ctx["approval_initiator"]["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-A-1", certifying_secretary_ref="SEC-A-2"),
            make_board_secretary_headers(ctx["org_a"]["id"]),
        )
    )
    ctx["approval_target"] = validate_success(
        api.certify_board_approval(
            ctx["approval_target"]["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-B-1", certifying_secretary_ref="SEC-B-2"),
            make_board_secretary_headers(ctx["org_b"]["id"]),
        )
    )
    ctx["deal"] = read_deal(api, ctx["deal"]["id"])
    return ctx


def setup_deal_integration(api: ApiClient, ctx: Optional[Json] = None, **filing_overrides: Any) -> Json:
    """Submit the attorney-general filing and record an approval, which releases the
    deal REGULATORY_REVIEW -> INTEGRATION."""
    ctx = {} if ctx is None else ctx
    if ctx.get("deal", {}).get("status") not in ("REGULATORY_REVIEW", "INTEGRATION"):
        ctx = setup_deal_regulatory_review(api, ctx)
    deal_id = ctx["deal"]["id"]
    if ctx["deal"]["status"] == "REGULATORY_REVIEW":
        ctx["filing"] = validate_success(
            api.create_ag_filing(f.ag_filing_payload(deal_id, **filing_overrides), TRUST_COUNSEL),
            201,
        )
        ctx["filing"] = validate_success(
            api.record_ag_decision(
                ctx["filing"]["id"], f.ag_decision_payload("APPROVED"), CHARITIES_REGULATOR
            )
        )
    ctx["deal"] = read_deal(api, deal_id)
    return ctx


# ----------------------------------------------------------------------
# Restricted-fund branch helpers
# ----------------------------------------------------------------------
def setup_fund_consent_granted(api: ApiClient, org_id: str, **overrides: Any) -> Json:
    """Walk a fund HELD -> CONSENT_SOUGHT -> CONSENT_GRANTED."""
    fund = create_fund(api, org_id, **overrides)
    validate_success(api.seek_consent(fund["id"], f.seek_consent_payload(), TRUST_COUNSEL))
    return validate_success(
        api.record_consent(fund["id"], f.record_consent_payload("GRANTED"), TRUST_COUNSEL)
    )


def setup_fund_consent_denied(api: ApiClient, org_id: str, **overrides: Any) -> Json:
    """Walk a fund HELD -> CONSENT_SOUGHT -> CONSENT_DENIED."""
    fund = create_fund(api, org_id, **overrides)
    validate_success(api.seek_consent(fund["id"], f.seek_consent_payload(), TRUST_COUNSEL))
    return validate_success(
        api.record_consent(fund["id"], f.record_consent_payload("DENIED"), TRUST_COUNSEL)
    )


def setup_fund_modified(api: ApiClient, org_id: str, **overrides: Any) -> Json:
    """Walk a fund down the judicial route to MODIFIED via CONSENT_DENIED."""
    fund = setup_fund_consent_denied(api, org_id, **overrides)
    validate_success(api.file_petition(fund["id"], f.file_petition_payload(), TRUST_COUNSEL))
    return validate_success(
        api.record_court_decision(
            fund["id"], f.court_decision_payload("GRANTED"), TRUST_COUNSEL
        )
    )


def setup_fund_petition_filed(api: ApiClient, org_id: str, **overrides: Any) -> Json:
    """Walk a fund to PETITION_FILED via CONSENT_DENIED."""
    fund = setup_fund_consent_denied(api, org_id, **overrides)
    return validate_success(
        api.file_petition(fund["id"], f.file_petition_payload(), TRUST_COUNSEL)
    )


def transfer_fund(api: ApiClient, fund_id: str, deal_id: str, basis: str = "DONOR_CONSENT") -> Json:
    return validate_success(
        api.transfer_restricted_fund(fund_id, f.transfer_payload(deal_id, basis), TRUST_COUNSEL)
    )


def unwind_fund(api: ApiClient, fund_id: str) -> Json:
    return validate_success(
        api.unwind_restricted_fund(fund_id, f.unwind_payload(), TRUST_COUNSEL)
    )


# ----------------------------------------------------------------------
# Integration-task helpers
# ----------------------------------------------------------------------
def create_task(api: ApiClient, deal_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_integration_task(
            f.integration_task_payload(deal_id, **overrides), INTEGRATION_MANAGER
        ),
        201,
    )


def complete_task(api: ApiClient, task_id: str) -> Json:
    validate_success(api.start_integration_task(task_id, f.start_task_payload(), INTEGRATION_MANAGER))
    return validate_success(
        api.complete_integration_task(task_id, f.complete_task_payload(), INTEGRATION_MANAGER)
    )


def dossier(api: ApiClient, deal_id: str) -> Json:
    return validate_success(api.get_dossier(deal_id, PLATFORM_ADMIN))


def lenient_data(response: Any) -> Any:
    """Best-effort payload read, for preconditions where the shape is not the point."""
    return get_success_data(response)
