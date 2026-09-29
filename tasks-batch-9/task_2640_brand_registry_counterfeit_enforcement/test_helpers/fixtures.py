"""Composite setup helpers.

Most interesting assertions in this domain need the system driven through five
to fifteen calls first: a brand, a registration, a marketplace enrolment, an
authorized-representative designation, a seller, a screened listing, a
substantiated claim, a sealed evidence package and a filed notice. These helpers
encapsulate those preambles so tests carry assertions only.

Setup uses the lenient ``get_success_data`` validator so a broken precondition
surfaces as a setup failure rather than a confusing assertion failure.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .assertions import add_business_days
from .constants import (
    AUTHENTICATION_RESULT_COUNTERFEIT,
    CLOCK_EPOCH,
    DECISION_REJECTED,
    DECISION_REMOVED,
    ITEM_COPYRIGHT_DEPOSIT_COPY,
    ITEM_CUSTOMER_COMPLAINT,
    ITEM_LAB_AUTHENTICATION_REPORT,
    ITEM_LISTING_SCREENSHOT,
    ITEM_MARK_COMPARISON,
    ITEM_PRICE_HISTORY_EXPORT,
    ITEM_REGISTRATION_CERTIFICATE,
    ITEM_SELLER_PROFILE_SNAPSHOT,
    ITEM_SHIPPING_LABEL_PHOTO,
    ITEM_TEST_BUY_INVOICE,
    ITEM_WORK_COMPARISON,
    MARKETPLACE_AMZ,
    RESOLUTION_ACCEPTED,
    RESPONSE_KIND_DENIAL,
    SCOPE_SUBMIT_TAKEDOWN,
    SOURCE_KIND_BORDER_SEIZURE,
    TAKEDOWN_DECISION_SLA_BUSINESS_DAYS,
    VIOLATION_TYPE_COUNTERFEIT,
    VIOLATION_TYPE_TRADEMARK,
)
from .test_users import TEST_USERS, make_authorized_representative_headers

ADMIN = TEST_USERS["brand_administrator_headers"]
ANALYST = TEST_USERS["enforcement_analyst_headers"]
LIAISON = TEST_USERS["marketplace_liaison_headers"]
CUSTOMS = TEST_USERS["customs_coordinator_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]

# Optional (supporting) evidence types, in a stable order for padding a package.
SUPPORTING_ITEM_TYPES = [
    ITEM_SELLER_PROFILE_SNAPSHOT,
    ITEM_PRICE_HISTORY_EXPORT,
    ITEM_CUSTOMER_COMPLAINT,
    ITEM_SHIPPING_LABEL_PHOTO,
]

REQUIRED_ITEMS_BY_VIOLATION = {
    VIOLATION_TYPE_COUNTERFEIT: [
        ITEM_TEST_BUY_INVOICE,
        ITEM_LAB_AUTHENTICATION_REPORT,
        ITEM_LISTING_SCREENSHOT,
        ITEM_REGISTRATION_CERTIFICATE,
    ],
    VIOLATION_TYPE_TRADEMARK: [
        ITEM_LISTING_SCREENSHOT,
        ITEM_REGISTRATION_CERTIFICATE,
        ITEM_MARK_COMPARISON,
    ],
    "COPYRIGHT": [
        ITEM_LISTING_SCREENSHOT,
        ITEM_COPYRIGHT_DEPOSIT_COPY,
        ITEM_WORK_COMPARISON,
    ],
}


# --------------------------------------------------------------------- clock ---


def set_clock(api: ApiClient, to_iso8601: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Move the logical clock. Mutates no rows; returns the resulting reading."""
    return get_success_data(api.set_clock(to_iso8601, headers=headers or ADMIN))


# ------------------------------------------------------------------- tier one ---


def create_brand(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_brand(f.brand_payload(**overrides), headers=ADMIN))


def read_brand(api: ApiClient, brand_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_brand(brand_id, headers=headers or ADMIN))


def create_registration(api: ApiClient, brand_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_registration(f.registration_payload(brand_id, **overrides), headers=ADMIN))


def create_enrollment(api: ApiClient, brand_id: str, registration_id: str,
                      expected_brand_version: Optional[int] = None, **overrides) -> Dict[str, Any]:
    """Enrol the brand, quoting the brand's current version unless told otherwise."""
    if expected_brand_version is None:
        expected_brand_version = read_brand(api, brand_id)["version"]
    payload = f.enrollment_payload(brand_id, registration_id, expected_brand_version, **overrides)
    return get_success_data(api.create_enrollment(payload, headers=ADMIN))


def activate_enrollment(api: ApiClient, enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_enrollment(enrollment_id, headers=LIAISON))


def suspend_enrollment(api: ApiClient, enrollment_id: str, reason_code: str) -> Dict[str, Any]:
    return get_success_data(api.suspend_enrollment(enrollment_id, reason_code, headers=LIAISON))


def create_representative(api: ApiClient, enrollment_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_representative(f.representative_payload(enrollment_id, **overrides), headers=ADMIN))


def create_seller(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_seller(f.seller_payload(**overrides), headers=ANALYST))


def read_seller(api: ApiClient, seller_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_seller(seller_id, headers=headers or ANALYST))


def create_listing(api: ApiClient, brand_id: str, seller_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_listing(f.listing_payload(brand_id, seller_id, **overrides), headers=ANALYST))


def read_listing(api: ApiClient, listing_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_listing(listing_id, headers=headers or ANALYST))


def screen_listing(api: ApiClient, listing_id: str, image_match_score: float = 0.92,
                   text_match_score: float = 0.88) -> Dict[str, Any]:
    return get_success_data(api.screen_listing(
        listing_id, f.screen_payload(image_match_score, text_match_score), headers=ANALYST))


def create_claim(api: ApiClient, brand_id: str, listing_id: str, registration_id: str,
                 **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_claim(
        f.claim_payload(brand_id, listing_id, registration_id, **overrides), headers=ANALYST))


def read_claim(api: ApiClient, claim_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_claim(claim_id, headers=headers or ANALYST))


def substantiate_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.substantiate_claim(claim_id, headers=ANALYST))


def create_test_buy(api: ApiClient, claim_id: str, purchase_price_cents: int = 4200,
                    shipping_cents: int = 700, lab_fee_cents: int = 0, **overrides) -> Dict[str, Any]:
    payload = f.test_buy_payload(purchase_price_cents, shipping_cents, lab_fee_cents, **overrides)
    return get_success_data(api.create_test_buy(claim_id, payload, headers=ANALYST))


def receive_test_buy(api: ApiClient, test_buy_id: str, lot_code: str = "LOT-2026-A",
                     chain_of_custody_ref: Optional[str] = "COC-1") -> Dict[str, Any]:
    return get_success_data(
        api.receive_test_buy(test_buy_id, lot_code, chain_of_custody_ref, headers=ANALYST))


def authenticate_test_buy(api: ApiClient, test_buy_id: str,
                          authentication_result: str = AUTHENTICATION_RESULT_COUNTERFEIT,
                          lab_ref: str = "LAB-1") -> Dict[str, Any]:
    return get_success_data(
        api.authenticate_test_buy(test_buy_id, authentication_result, lab_ref, headers=ANALYST))


def create_evidence_package(api: ApiClient, claim_id: str,
                            expected_claim_version: Optional[int] = None, **overrides) -> Dict[str, Any]:
    """Open a package on the claim, quoting the claim's live version by default."""
    if expected_claim_version is None:
        expected_claim_version = read_claim(api, claim_id)["version"]
    payload = f.evidence_package_payload(claim_id, expected_claim_version, **overrides)
    return get_success_data(api.create_evidence_package(payload, headers=ANALYST))


def read_evidence_package(api: ApiClient, package_id: str,
                          headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_evidence_package(package_id, headers=headers or ANALYST))


def append_items(api: ApiClient, package_id: str,
                 items: Sequence[Tuple[str, str]]) -> Dict[str, Any]:
    last: Dict[str, Any] = {}
    for item_type, item_ref in items:
        last = get_success_data(
            api.append_evidence_item(package_id, item_type, item_ref, headers=ANALYST))
    return last


def seal_evidence_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return get_success_data(api.seal_evidence_package(package_id, headers=ANALYST))


def fill_and_seal_package(api: ApiClient, claim_id: str,
                          claimed_violation_type: Optional[str] = None,
                          optional_count: int = 2, tag: str = "1",
                          expected_claim_version: Optional[int] = None) -> Dict[str, Any]:
    """Open a package, cover every required type, pad with optional items, seal it.

    PRD §3.7: "Which of those are mandatory depends on the parent claim's
    `claimed_violation_type`." The mandatory set is therefore read off the claim
    itself unless a caller deliberately overrides it, so a package always covers
    the set the server will score it against.

    Full coverage plus two optional items scores 0.8500, which clears the 0.8000
    seal threshold.
    """
    if claimed_violation_type is None:
        claimed_violation_type = read_claim(api, claim_id)["claimed_violation_type"]
    package = create_evidence_package(api, claim_id, expected_claim_version)
    items: List[Tuple[str, str]] = [
        (item_type, f"{item_type[:3]}-{tag}-{i}")
        for i, item_type in enumerate(REQUIRED_ITEMS_BY_VIOLATION[claimed_violation_type], start=1)
    ]
    items += [(item_type, f"{item_type[:3]}-{tag}-opt{i}")
              for i, item_type in enumerate(SUPPORTING_ITEM_TYPES[:optional_count], start=1)]
    append_items(api, package["id"], items)
    return seal_evidence_package(api, package["id"])


def create_takedown(api: ApiClient, enrollment_id: str, claim_id: str, evidence_package_id: str,
                    headers: Optional[Dict] = None) -> Dict[str, Any]:
    payload = f.takedown_payload(enrollment_id, claim_id, evidence_package_id)
    return get_success_data(api.create_takedown(payload, headers=headers or ANALYST))


def read_takedown(api: ApiClient, takedown_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_takedown(takedown_id, headers=headers or ANALYST))


def submit_takedown(api: ApiClient, takedown_id: str, representative_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_takedown(
        takedown_id, headers=make_authorized_representative_headers(representative_id)))


def decide_takedown(api: ApiClient, takedown_id: str, decision: str = DECISION_REMOVED,
                    marketplace_case_ref: Optional[str] = None) -> Dict[str, Any]:
    payload = f.marketplace_decision_payload(decision, marketplace_case_ref)
    return get_success_data(api.decide_takedown(
        takedown_id, payload["decision"], payload["marketplace_case_ref"], headers=LIAISON))


def resubmit_takedown(api: ApiClient, takedown_id: str, evidence_package_id: str,
                      representative_id: str) -> Dict[str, Any]:
    return get_success_data(api.resubmit_takedown(
        takedown_id, evidence_package_id,
        headers=make_authorized_representative_headers(representative_id)))


def create_counter_notice(api: ApiClient, takedown_id: str, seller_id: str,
                          **overrides) -> Dict[str, Any]:
    payload = f.counter_notice_payload(takedown_id, seller_id, **overrides)
    return get_success_data(api.create_counter_notice(payload, headers=LIAISON))


def resolve_counter_notice(api: ApiClient, counter_notice_id: str,
                           resolution: str = RESOLUTION_ACCEPTED,
                           rebuttal_ref: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(api.resolve_counter_notice(
        counter_notice_id, resolution, rebuttal_ref, headers=LIAISON))


def create_case(api: ApiClient, brand_id: str, seller_id: str) -> Dict[str, Any]:
    return get_success_data(api.create_case(f.case_payload(brand_id, seller_id), headers=COUNSEL))


def read_case(api: ApiClient, case_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_case(case_id, headers=headers or COUNSEL))


def send_cease_desist(api: ApiClient, case_id: str, representative_id: str,
                      letter_ref: str = "CD-1") -> Dict[str, Any]:
    return get_success_data(api.send_cease_desist(
        case_id, letter_ref, headers=make_authorized_representative_headers(representative_id)))


def record_case_response(api: ApiClient, case_id: str, response_ref: str = "RESP-1",
                         response_kind: str = RESPONSE_KIND_DENIAL) -> Dict[str, Any]:
    return get_success_data(
        api.record_case_response(case_id, response_ref, response_kind, headers=COUNSEL))


def authorize_litigation(api: ApiClient, case_id: str, representative_id: str,
                         authorization_ref: str = "AUTH-1") -> Dict[str, Any]:
    return get_success_data(api.authorize_litigation(
        case_id, authorization_ref,
        headers=make_authorized_representative_headers(representative_id)))


def create_recordation(api: ApiClient, brand_id: str, registration_id: str,
                       **overrides) -> Dict[str, Any]:
    payload = f.recordation_payload(brand_id, registration_id, **overrides)
    return get_success_data(api.create_recordation(payload, headers=CUSTOMS))


def record_recordation(api: ApiClient, recordation_id: str,
                       recordation_number: str = "CBP-0001") -> Dict[str, Any]:
    return get_success_data(
        api.record_recordation(recordation_id, recordation_number, headers=CUSTOMS))


def create_recorded_recordation(api: ApiClient, brand_id: str, registration_id: str,
                                recordation_number: str = "CBP-0001", **overrides) -> Dict[str, Any]:
    """Draft a customs recordation and confirm it with the border authority."""
    draft = create_recordation(api, brand_id, registration_id, **overrides)
    return record_recordation(api, draft["id"], recordation_number)


def create_border_seizure_investigation(api: ApiClient, brand_id: str, recordation_id: str,
                                        seller_id: Optional[str] = None,
                                        lot_code: str = "LOT-2026-A", **overrides) -> Dict[str, Any]:
    payload = f.border_seizure_investigation_payload(
        brand_id, recordation_id, lot_code=lot_code, **overrides)
    if seller_id is not None:
        payload["seller_id"] = seller_id
    return get_success_data(api.create_investigation(payload, headers=CUSTOMS))


def submit_investigation_evidence(api: ApiClient, investigation_id: str,
                                  evidence_ref: str = "EVID-1",
                                  suspected_distributor_ref: str = "DIST-1") -> Dict[str, Any]:
    return get_success_data(api.submit_investigation_evidence(
        investigation_id, evidence_ref, suspected_distributor_ref, headers=ANALYST))


def conclude_investigation(api: ApiClient, investigation_id: str, outcome: str,
                           findings_ref: str = "FIND-1") -> Dict[str, Any]:
    return get_success_data(
        api.conclude_investigation(investigation_id, outcome, findings_ref, headers=CUSTOMS))


def run_sweep(api: ApiClient, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.run_enforcement_sweep(headers=headers or LIAISON))


def read_metrics(api: ApiClient, brand_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_enforcement_metrics(brand_id, headers=headers or ANALYST))


# --------------------------------------------------------- composite scenarios ---


def setup_enrolled_brand(api: ApiClient, clock: Optional[str] = None,
                         brand: Optional[Dict] = None,
                         registration: Optional[Dict] = None,
                         enrollment: Optional[Dict] = None,
                         representative: Optional[Dict] = None,
                         activate: bool = True) -> Dict[str, Any]:
    """Brand, REGISTERED registration, marketplace enrolment and one designation.

    Returns a context dict keyed ``brand``, ``registration``, ``enrollment`` and
    ``representative`` (the designation is created only when the enrolment is
    activated, since a designation demands an ACTIVE enrolment).
    """
    if clock:
        set_clock(api, clock)
    ctx: Dict[str, Any] = {}
    ctx["brand"] = create_brand(api, **(brand or {}))
    ctx["registration"] = create_registration(api, ctx["brand"]["id"], **(registration or {}))
    ctx["enrollment"] = create_enrollment(
        api, ctx["brand"]["id"], ctx["registration"]["id"], **(enrollment or {}))
    if activate:
        ctx["enrollment"] = activate_enrollment(api, ctx["enrollment"]["id"])
        ctx["representative"] = create_representative(
            api, ctx["enrollment"]["id"], **(representative or {}))
    return ctx


def setup_two_scope_representatives(api: ApiClient, ctx: Dict[str, Any],
                                    effective_from: str = "2026-08-01T00:00:00Z",
                                    effective_to: Optional[str] = "2027-08-01T00:00:00Z") -> Dict[str, Any]:
    """A SUBMIT_TAKEDOWN designation and an AUTHORIZE_LITIGATION designation.

    The two authority scopes do not intersect, so both may hold the same window.
    Segregation of duties needs two distinct identities.
    """
    ctx["representative_takedown"] = create_representative(
        api, ctx["enrollment"]["id"], authority_scope="SUBMIT_TAKEDOWN",
        effective_from=effective_from, effective_to=effective_to,
        power_of_attorney_ref="POA-TAKEDOWN")
    ctx["representative_litigation"] = create_representative(
        api, ctx["enrollment"]["id"], authority_scope="AUTHORIZE_LITIGATION",
        effective_from=effective_from, effective_to=effective_to,
        power_of_attorney_ref="POA-LITIGATION")
    return ctx


def setup_flagged_listing(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                          clock: Optional[str] = None,
                          price_cents: int = 3000,
                          image_match_score: float = 0.92,
                          text_match_score: float = 0.88,
                          seller: Optional[Dict] = None,
                          listing: Optional[Dict] = None,
                          **enrolled_kwargs) -> Dict[str, Any]:
    """Enrolled brand plus a seller and a screened listing.

    At a 10000-cent authorized MSRP a 3000-cent listing deviates 0.7000, and
    matcher output of 0.92 / 0.88 scores 0.8620, which flags the listing.
    """
    ctx = ctx if ctx is not None else setup_enrolled_brand(api, clock=clock, **enrolled_kwargs)
    ctx.setdefault("seller", create_seller(api, **(seller or {})))
    ctx["listing"] = create_listing(
        api, ctx["brand"]["id"], ctx["seller"]["id"], price_cents=price_cents, **(listing or {}))
    ctx["listing"] = screen_listing(api, ctx["listing"]["id"], image_match_score, text_match_score)
    return ctx


def setup_claim(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                claimed_violation_type: str = VIOLATION_TYPE_TRADEMARK,
                **flagged_kwargs) -> Dict[str, Any]:
    """Flagged listing plus a DRAFT claim asserting the brand's registration."""
    ctx = ctx if ctx is not None else setup_flagged_listing(api, **flagged_kwargs)
    ctx["claim"] = create_claim(
        api, ctx["brand"]["id"], ctx["listing"]["id"], ctx["registration"]["id"],
        claimed_violation_type=claimed_violation_type)
    ctx["claimed_violation_type"] = claimed_violation_type
    return ctx


def setup_substantiated_claim(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                              clock: Optional[str] = None,
                              claimed_violation_type: str = VIOLATION_TYPE_TRADEMARK,
                              **flagged_kwargs) -> Dict[str, Any]:
    """A claim promoted to SUBSTANTIATED with no test buy involved.

    A listing priced at 0 cents deviates 1.0000, and matcher output of 1.00 /
    1.00 scores exactly 1.0000. Against a REGISTERED principal-register
    registration in the listing's own class the base score is
    60 * 1.0000 + 25 * 1.00 + 15 * 0 = 85.00, which is exactly the promotion
    threshold.
    """
    if ctx is None:
        flagged_kwargs.setdefault("price_cents", 0)
        flagged_kwargs.setdefault("image_match_score", 1.00)
        flagged_kwargs.setdefault("text_match_score", 1.00)
        ctx = setup_flagged_listing(api, clock=clock, **flagged_kwargs)
    ctx = setup_claim(api, ctx, claimed_violation_type=claimed_violation_type)
    ctx["claim"] = substantiate_claim(api, ctx["claim"]["id"])
    return ctx


def setup_drafted_takedown(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                           optional_count: int = 2, tag: str = "1",
                           **substantiated_kwargs) -> Dict[str, Any]:
    """Substantiated claim, sealed evidence package and a DRAFT takedown notice."""
    ctx = ctx if ctx is not None else setup_substantiated_claim(api, **substantiated_kwargs)
    ctx["package"] = fill_and_seal_package(
        api, ctx["claim"]["id"],
        claimed_violation_type=ctx.get("claimed_violation_type", VIOLATION_TYPE_TRADEMARK),
        optional_count=optional_count, tag=tag)
    ctx["takedown"] = create_takedown(
        api, ctx["enrollment"]["id"], ctx["claim"]["id"], ctx["package"]["id"])
    return ctx


def setup_submitted_takedown(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                             **drafted_kwargs) -> Dict[str, Any]:
    """A takedown notice filed with the marketplace by its representative."""
    ctx = ctx if ctx is not None else setup_drafted_takedown(api, **drafted_kwargs)
    ctx["takedown"] = submit_takedown(
        api, ctx["takedown"]["id"], ctx["representative"]["id"])
    return ctx


def setup_removed_takedown(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                           marketplace_case_ref: Optional[str] = None,
                           **submitted_kwargs) -> Dict[str, Any]:
    """A notice the marketplace approved, which attributes the removal strike."""
    ctx = ctx if ctx is not None else setup_submitted_takedown(api, **submitted_kwargs)
    ctx["takedown"] = decide_takedown(
        api, ctx["takedown"]["id"], DECISION_REMOVED, marketplace_case_ref)
    return ctx


def setup_rejected_takedown(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                            marketplace_case_ref: Optional[str] = None,
                            **submitted_kwargs) -> Dict[str, Any]:
    """A notice the marketplace refused, which releases the listing with no strike."""
    ctx = ctx if ctx is not None else setup_submitted_takedown(api, **submitted_kwargs)
    ctx["takedown"] = decide_takedown(
        api, ctx["takedown"]["id"], DECISION_REJECTED, marketplace_case_ref)
    return ctx


def setup_counter_noticed_takedown(api: ApiClient, ctx: Optional[Dict[str, Any]] = None,
                                   clock: Optional[str] = None,
                                   **removed_kwargs) -> Dict[str, Any]:
    """A removed notice against which the marketplace relayed a counter notice."""
    ctx = ctx if ctx is not None else setup_removed_takedown(api, **removed_kwargs)
    if clock:
        set_clock(api, clock)
    ctx["counter_notice"] = create_counter_notice(
        api, ctx["takedown"]["id"], ctx["seller"]["id"])
    ctx["takedown"] = read_takedown(api, ctx["takedown"]["id"])
    return ctx


def setup_second_removal_on_same_seller(api: ApiClient, ctx: Dict[str, Any],
                                        clock: Optional[str] = None,
                                        tag: str = "2") -> Dict[str, Any]:
    """A second listing, claim, package and approved notice on the same seller.

    Two fresh removal strikes total 25.10, which crosses the escalation
    threshold and takes the seller to UNDER_INVESTIGATION.
    """
    if clock:
        set_clock(api, clock)
    listing = create_listing(api, ctx["brand"]["id"], ctx["seller"]["id"], price_cents=0)
    listing = screen_listing(api, listing["id"], 1.00, 1.00)
    claim = create_claim(api, ctx["brand"]["id"], listing["id"], ctx["registration"]["id"],
                         claimed_violation_type=VIOLATION_TYPE_TRADEMARK)
    claim = substantiate_claim(api, claim["id"])
    package = fill_and_seal_package(api, claim["id"],
                                    claimed_violation_type=VIOLATION_TYPE_TRADEMARK, tag=tag)
    takedown = create_takedown(api, ctx["enrollment"]["id"], claim["id"], package["id"])
    takedown = submit_takedown(api, takedown["id"], ctx["representative"]["id"])
    takedown = decide_takedown(api, takedown["id"], DECISION_REMOVED, f"MP-{tag}")
    ctx["listing_2"] = read_listing(api, listing["id"])
    ctx["claim_2"] = read_claim(api, claim["id"])
    ctx["package_2"] = package
    ctx["takedown_2"] = takedown
    return ctx


def setup_escalated_seller_via_diversion(api: ApiClient, ctx: Dict[str, Any],
                                         lot_code: str = "LOT-DIV-1",
                                         recordation_number: str = "CBP-9001") -> Dict[str, Any]:
    """Drive one seller to UNDER_INVESTIGATION with a single confirmed diversion.

    A confirmed border diversion is worth 25.15 strike points on its own, which
    is above the 25.00 escalation threshold.
    """
    ctx["recordation"] = create_recorded_recordation(
        api, ctx["brand"]["id"], ctx["registration"]["id"], recordation_number)
    investigation = create_border_seizure_investigation(
        api, ctx["brand"]["id"], ctx["recordation"]["id"],
        seller_id=ctx["seller"]["id"], lot_code=lot_code)
    submit_investigation_evidence(api, investigation["id"])
    ctx["investigation"] = conclude_investigation(
        api, investigation["id"], "DIVERSION_CONFIRMED", "FIND-DIV-1")
    ctx["seller"] = read_seller(api, ctx["seller"]["id"])
    return ctx


def expected_decision_due_at(submitted_at: str, marketplace_code: str = MARKETPLACE_AMZ) -> str:
    """The marketplace decision deadline is the SLA in business days from filing."""
    return add_business_days(submitted_at, TAKEDOWN_DECISION_SLA_BUSINESS_DAYS[marketplace_code])
