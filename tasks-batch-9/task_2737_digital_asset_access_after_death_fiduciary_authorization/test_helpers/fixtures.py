"""
Composite setup builders.

Every test starts against an empty database whose logical clock sits at the
fresh-server epoch, so every precondition has to be built from scratch. The
helpers here climb the domain in tiers, each tier reusing the one below it:

  Tier 1 — primitives: move the clock, register a provider, open an estate.
  Tier 2 — an authorized estate: appointed fiduciary, verified death
           certificate, verified letters of authority.
  Tier 3 — inventory: digital assets and subscription terms.
  Tier 4 — authority: a platform request driven to APPROVED, which grants
           authority and discloses the catalogue.
  Tier 5 — downstream: cancellation orders, refund claims, valuation runs,
           disposition elections.

Setup helpers use the lenient success reader, so a broken precondition fails
loudly as a setup error rather than as a confusing assertion deep in a test.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    BASIS_DATE_OF_DEATH,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_SUBSCRIPTION,
    CLAIM_ACTION_START_REVIEW,
    CLOCK_EPOCH,
    DECISION_APPROVED,
    DOC_ACTION_VERIFY,
    ELECTION_MEMORIALIZE,
    EL_ACTION_SUBMIT,
    ORDER_ACTION_CONFIRM,
    ORDER_ACTION_REQUEST,
    REQ_ACTION_DECIDE,
    REQ_ACTION_START_REVIEW,
    REQ_ACTION_SUBMIT,
    REQUEST_TYPE_CATALOG_ACCESS,
    SCOPE_CATALOG_ONLY,
)
from .test_users import (
    COURT_REGISTRAR_HEADERS,
    ESTATE_ADMIN_HEADERS,
    make_fiduciary_headers,
    make_platform_compliance_headers,
)


# ─── Tier 1: primitives ──────────────────────────────────────────────────────
def set_clock(api: ApiClient, to_iso8601: str = CLOCK_EPOCH) -> str:
    """Move the logical clock and return the reading the server reports back."""
    data = get_success_data(api.set_clock(to_iso8601, ESTATE_ADMIN_HEADERS))
    return data["current_utc"]


def register_platform(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register the default cloud-storage provider."""
    return get_success_data(api.create_platform(f.platform_payload(**overrides), ESTATE_ADMIN_HEADERS))


def register_subscription_platform(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_platform(f.subscription_platform_payload(**overrides), ESTATE_ADMIN_HEADERS)
    )


def register_financial_platform(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_platform(f.financial_platform_payload(**overrides), ESTATE_ADMIN_HEADERS)
    )


def register_loyalty_platform(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_platform(f.loyalty_platform_payload(**overrides), ESTATE_ADMIN_HEADERS)
    )


def register_social_platform(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_platform(f.social_platform_payload(**overrides), ESTATE_ADMIN_HEADERS)
    )


def patch_platform(api: ApiClient, platform_id: str, **changes: Any) -> Dict[str, Any]:
    return get_success_data(api.update_platform(platform_id, dict(changes), ESTATE_ADMIN_HEADERS))


def open_estate(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Open an estate in its INTAKE phase."""
    return get_success_data(api.create_estate(f.estate_payload(**overrides), ESTATE_ADMIN_HEADERS))


def appoint_fiduciary(api: ApiClient, estate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Appoint a fiduciary; letters start PENDING until a document is verified."""
    return get_success_data(
        api.create_fiduciary(estate_id, f.fiduciary_payload(**overrides), COURT_REGISTRAR_HEADERS)
    )


def add_document(api: ApiClient, estate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_document(estate_id, payload, COURT_REGISTRAR_HEADERS))


def verify_document(api: ApiClient, document_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_document(
            document_id, f.document_transition_payload(DOC_ACTION_VERIFY), COURT_REGISTRAR_HEADERS
        )
    )


def revoke_document(api: ApiClient, document_id: str, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_document(
            document_id,
            f.document_transition_payload("REVOKE", revocation_reason=reason),
            COURT_REGISTRAR_HEADERS,
        )
    )


# ─── Tier 2: an estate that holds authority ──────────────────────────────────
@dataclass
class EstateContext:
    """Everything a test needs to keep acting on one estate."""

    estate_id: str
    fiduciary_id: str
    death_certificate_id: str
    letters_id: str
    fiduciary_headers: Dict[str, str] = field(default_factory=dict)
    extra_fiduciary_ids: List[str] = field(default_factory=list)

    @property
    def fid_headers(self) -> Dict[str, str]:
        return self.fiduciary_headers


def authorized_estate(
    api: ApiClient,
    court_case_number: str,
    *,
    date_of_death: str = "2026-02-14",
    decedent_name: str = "Rowan Ives",
    domicile_state: str = "CA",
    reference_suffix: Optional[str] = None,
    verify_death_certificate: bool = True,
    verify_letters: bool = True,
) -> EstateContext:
    """
    Open an estate, appoint one fiduciary, file a death certificate and a
    letters-of-authority document, and verify both by default so that the
    fiduciary holds ISSUED letters and the estate reads AUTHORIZED.
    """
    suffix = reference_suffix or court_case_number
    estate = open_estate(
        api,
        decedent_name=decedent_name,
        date_of_death=date_of_death,
        domicile_state=domicile_state,
        court_case_number=court_case_number,
    )
    fid = appoint_fiduciary(api, estate["id"], court_reference=f"APPT-{suffix}")
    dc = add_document(
        api, estate["id"], f.document_payload(reference_number=f"DC-{suffix}", jurisdiction=domicile_state)
    )
    if verify_death_certificate:
        verify_document(api, dc["id"])
    loa = add_document(
        api,
        estate["id"],
        f.letters_document_payload(
            fid["id"], reference_number=f"LOA-{suffix}", jurisdiction=domicile_state
        ),
    )
    if verify_letters:
        verify_document(api, loa["id"])
    return EstateContext(
        estate_id=estate["id"],
        fiduciary_id=fid["id"],
        death_certificate_id=dc["id"],
        letters_id=loa["id"],
        fiduciary_headers=make_fiduciary_headers(fid["id"]),
    )


def add_second_fiduciary(
    api: ApiClient, ctx: EstateContext, suffix: str, *, verify_letters: bool = True
) -> Dict[str, Any]:
    """Appoint a co-fiduciary with its own letters document, for countersigning."""
    fid = appoint_fiduciary(
        api,
        ctx.estate_id,
        full_name="Robin Ives",
        appointment_type="ADMINISTRATOR",
        court_reference=f"APPT-{suffix}",
    )
    loa = add_document(
        api, ctx.estate_id, f.letters_document_payload(fid["id"], reference_number=f"LOA-{suffix}")
    )
    if verify_letters:
        verify_document(api, loa["id"])
    ctx.extra_fiduciary_ids.append(fid["id"])
    fid["letters_document_id"] = loa["id"]
    return fid


# ─── Tier 3: inventory ───────────────────────────────────────────────────────
def add_asset(
    api: ApiClient, ctx: EstateContext, platform_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Add one digital asset to the estate, as its fiduciary."""
    return get_success_data(
        api.create_digital_asset(
            ctx.estate_id, f.digital_asset_payload(platform_id, **overrides), ctx.fiduciary_headers
        )
    )


def add_subscription_asset(
    api: ApiClient,
    ctx: EstateContext,
    platform_id: str,
    *,
    account_handle: str = "stream-premium",
    **overrides: Any,
) -> Dict[str, Any]:
    return add_asset(
        api,
        ctx,
        platform_id,
        category=CATEGORY_SUBSCRIPTION,
        account_handle=account_handle,
        quoted_value_cents=overrides.pop("quoted_value_cents", 0),
        **overrides,
    )


def add_subscription_term(
    api: ApiClient, ctx: EstateContext, asset_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_subscription_term(
            asset_id, f.subscription_term_payload(**overrides), ctx.fiduciary_headers
        )
    )


def add_beneficiary(api: ApiClient, ctx: EstateContext, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_beneficiary_designation(
            ctx.estate_id, f.beneficiary_payload(**overrides), ctx.fiduciary_headers
        )
    )


def add_directive(api: ApiClient, ctx: EstateContext, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_authority_directive(
            ctx.estate_id, f.directive_payload(**overrides), ctx.fiduciary_headers
        )
    )


# ─── Tier 4: authority ───────────────────────────────────────────────────────
def draft_request(
    api: ApiClient,
    ctx: EstateContext,
    platform_id: str,
    platform_form_code: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a platform request against the estate's two verified documents."""
    return get_success_data(
        api.create_platform_request(
            ctx.estate_id,
            f.platform_request_payload(
                platform_id,
                ctx.death_certificate_id,
                ctx.letters_id,
                platform_form_code,
                **overrides,
            ),
            ctx.fiduciary_headers,
        )
    )


def submit_request(api: ApiClient, ctx: EstateContext, request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_platform_request(
            request_id, f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fiduciary_headers
        )
    )


def start_review(api: ApiClient, platform_id: str, request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_platform_request(
            request_id,
            f.request_transition_payload(REQ_ACTION_START_REVIEW),
            make_platform_compliance_headers(platform_id),
        )
    )


def decide_request(
    api: ApiClient,
    platform_id: str,
    request_id: str,
    decision: str = DECISION_APPROVED,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_platform_request(
            request_id,
            f.request_transition_payload(REQ_ACTION_DECIDE, decision=decision, **overrides),
            make_platform_compliance_headers(platform_id),
        )
    )


def approved_request(
    api: ApiClient,
    ctx: EstateContext,
    platform_id: str,
    platform_form_code: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Drive one request the whole way from DRAFT to APPROVED, which grants
    authority and discloses every asset of that provider on the estate.
    """
    request = draft_request(api, ctx, platform_id, platform_form_code, **overrides)
    submit_request(api, ctx, request["id"])
    start_review(api, platform_id, request["id"])
    return decide_request(api, platform_id, request["id"])


def grant_for_request(api: ApiClient, ctx: EstateContext, request_id: str) -> Dict[str, Any]:
    """Read back the authority grant an approval created."""
    rows, _ = _rows(api.list_authority_grants(ctx.fiduciary_headers, platform_request_id=request_id))
    assert rows, f"No authority grant exists for request {request_id}"
    return rows[0]


def cancellation_order_for_asset(
    api: ApiClient, ctx: EstateContext, asset_id: str
) -> Dict[str, Any]:
    """Read back the cancellation order an approval auto-created for an asset."""
    rows, _ = _rows(api.list_cancellation_orders(ctx.fiduciary_headers, asset_id=asset_id))
    assert rows, f"No cancellation order exists for asset {asset_id}"
    return rows[0]


def _rows(response) -> tuple:
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"Setup listing failed with HTTP {response.status_code}: {response.text}"
    )
    return body["data"], body["meta"]


# ─── Tier 5: downstream aggregates ───────────────────────────────────────────
def disclosed_cloud_asset(
    api: ApiClient, ctx: EstateContext, platform: Dict[str, Any], **asset_overrides: Any
) -> Dict[str, Any]:
    """One cloud-storage asset disclosed by an approved catalogue request."""
    asset = add_asset(api, ctx, platform["id"], category=CATEGORY_CLOUD_STORAGE, **asset_overrides)
    approved_request(api, ctx, platform["id"], platform["form_code"])
    return get_success_data(api.get_digital_asset(asset["id"], ctx.fiduciary_headers))


def confirmed_cancellation_order(
    api: ApiClient,
    ctx: EstateContext,
    platform_id: str,
    order_id: str,
    *,
    effective_date: str = "2026-03-15",
    platform_reference: str = "SO-CANCEL-1",
    auto_renew_stopped: bool = True,
) -> Dict[str, Any]:
    """Take an auto-created order from PENDING through REQUESTED to CONFIRMED."""
    get_success_data(
        api.transition_cancellation_order(
            order_id,
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date=effective_date),
            ctx.fiduciary_headers,
        )
    )
    return get_success_data(
        api.transition_cancellation_order(
            order_id,
            f.order_transition_payload(
                ORDER_ACTION_CONFIRM,
                platform_reference=platform_reference,
                auto_renew_stopped=auto_renew_stopped,
            ),
            make_platform_compliance_headers(platform_id),
        )
    )


def subscription_with_confirmed_order(
    api: ApiClient,
    ctx: EstateContext,
    platform: Dict[str, Any],
    *,
    account_handle: str = "stream-premium",
    term_overrides: Optional[Dict[str, Any]] = None,
    effective_date: str = "2026-03-15",
    platform_reference: str = "SO-CANCEL-1",
) -> Dict[str, Any]:
    """
    Build the whole refund runway: a subscription asset with a term, disclosed
    by an approved catalogue request, whose auto-created cancellation order is
    driven to CONFIRMED. Returns the asset, term and order.
    """
    asset = add_subscription_asset(api, ctx, platform["id"], account_handle=account_handle)
    term = add_subscription_term(api, ctx, asset["id"], **(term_overrides or {}))
    approved_request(api, ctx, platform["id"], platform["form_code"])
    order = cancellation_order_for_asset(api, ctx, asset["id"])
    order = confirmed_cancellation_order(
        api,
        ctx,
        platform["id"],
        order["id"],
        effective_date=effective_date,
        platform_reference=platform_reference,
    )
    return {"asset": asset, "term": term, "order": order}


def file_refund_claim(
    api: ApiClient,
    ctx: EstateContext,
    order_id: str,
    claimed_period_start: str,
    claimed_period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_refund_claim(
            order_id,
            f.refund_claim_payload(claimed_period_start, claimed_period_end, **overrides),
            ctx.fiduciary_headers,
        )
    )


def claim_in_platform_review(
    api: ApiClient,
    ctx: EstateContext,
    platform_id: str,
    order_id: str,
    claimed_period_start: str,
    claimed_period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    claim = file_refund_claim(
        api, ctx, order_id, claimed_period_start, claimed_period_end, **overrides
    )
    return get_success_data(
        api.transition_refund_claim(
            claim["id"],
            f.claim_transition_payload(CLAIM_ACTION_START_REVIEW),
            make_platform_compliance_headers(platform_id),
        )
    )


def estate_version(api: ApiClient, ctx: EstateContext) -> int:
    return get_success_data(api.get_estate(ctx.estate_id, ctx.fiduciary_headers))["version"]


def asset_version(api: ApiClient, ctx: EstateContext, asset_id: str) -> int:
    return get_success_data(api.get_digital_asset(asset_id, ctx.fiduciary_headers))["version"]


def computed_valuation_run(
    api: ApiClient, ctx: EstateContext, basis: str = BASIS_DATE_OF_DEATH
) -> Dict[str, Any]:
    """Create a valuation run using the estate's current version as the token."""
    version = estate_version(api, ctx)
    return get_success_data(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(version, basis=basis),
            ctx.fiduciary_headers,
        )
    )


def finalized_valuation_run(
    api: ApiClient, ctx: EstateContext, basis: str = BASIS_DATE_OF_DEATH, **overrides: Any
) -> Dict[str, Any]:
    run = computed_valuation_run(api, ctx, basis=basis)
    return get_success_data(
        api.transition_valuation_run(
            run["id"], f.run_transition_payload("FINALIZE", **overrides), ctx.fiduciary_headers
        )
    )


def draft_election(
    api: ApiClient, ctx: EstateContext, asset_id: str, election: str = ELECTION_MEMORIALIZE, **overrides: Any
) -> Dict[str, Any]:
    """Open a disposition election using the asset's current version as token."""
    version = asset_version(api, ctx, asset_id)
    return get_success_data(
        api.create_disposition_election(
            asset_id,
            f.election_payload(version, election=election, **overrides),
            ctx.fiduciary_headers,
        )
    )


def submitted_election(
    api: ApiClient, ctx: EstateContext, asset_id: str, election: str = ELECTION_MEMORIALIZE, **overrides: Any
) -> Dict[str, Any]:
    """Open and submit an election that needs no countersignature."""
    el = draft_election(api, ctx, asset_id, election=election, **overrides)
    return get_success_data(
        api.transition_disposition_election(
            el["id"], f.election_transition_payload(EL_ACTION_SUBMIT), ctx.fiduciary_headers
        )
    )


def executed_election(
    api: ApiClient,
    ctx: EstateContext,
    platform_id: str,
    asset_id: str,
    election: str = ELECTION_MEMORIALIZE,
    *,
    platform_confirmation_reference: str = "CV-CONF-1",
    **overrides: Any,
) -> Dict[str, Any]:
    el = submitted_election(api, ctx, asset_id, election=election, **overrides)
    return get_success_data(
        api.transition_disposition_election(
            el["id"],
            f.election_transition_payload(
                "EXECUTE", platform_confirmation_reference=platform_confirmation_reference
            ),
            make_platform_compliance_headers(platform_id),
        )
    )


# ─── Read-back shorthands ────────────────────────────────────────────────────
def read_estate(api: ApiClient, ctx: EstateContext) -> Dict[str, Any]:
    return get_success_data(api.get_estate(ctx.estate_id, ctx.fiduciary_headers))


def read_asset(api: ApiClient, ctx: EstateContext, asset_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_digital_asset(asset_id, ctx.fiduciary_headers))


def read_fiduciary(api: ApiClient, ctx: EstateContext, fiduciary_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fiduciary(fiduciary_id, ctx.fiduciary_headers))


def read_document(api: ApiClient, ctx: EstateContext, document_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_document(document_id, ctx.fiduciary_headers))


def read_request(api: ApiClient, ctx: EstateContext, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_platform_request(request_id, ctx.fiduciary_headers))


def read_grant(api: ApiClient, ctx: EstateContext, grant_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_authority_grant(grant_id, ctx.fiduciary_headers))


def read_term(api: ApiClient, ctx: EstateContext, term_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_subscription_term(term_id, ctx.fiduciary_headers))


def read_order(api: ApiClient, ctx: EstateContext, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cancellation_order(order_id, ctx.fiduciary_headers))


def read_claim(api: ApiClient, ctx: EstateContext, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_refund_claim(claim_id, ctx.fiduciary_headers))


def read_election(api: ApiClient, ctx: EstateContext, election_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_disposition_election(election_id, ctx.fiduciary_headers))


def read_run(api: ApiClient, ctx: EstateContext, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_valuation_run(run_id, ctx.fiduciary_headers))


def read_designation(api: ApiClient, ctx: EstateContext, designation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_beneficiary_designation(designation_id, ctx.fiduciary_headers))


def list_rows(response) -> List[Dict[str, Any]]:
    rows, _ = _rows(response)
    return rows


def list_meta(response) -> Dict[str, Any]:
    _, meta = _rows(response)
    return meta
