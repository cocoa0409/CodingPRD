"""Composite setup helpers.

Every test starts against an empty database, so each fixture builds its
preconditions from scratch using only the endpoints the PRD declares.
Setup calls go through get_success_data(), so a broken precondition surfaces as
a clear "Setup step failed" rather than a confusing assertion later on.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DOM_19,
    CLOCK_LISTED,
    REQUIRED_DOCUMENT_TYPES,
    TEST_DEFAULTS,
)
from .factories import (
    adjudicate_payload,
    clock_payload,
    create_bpo_vendor_payload,
    create_case_payload,
    create_hardship_package_payload,
    create_junior_lien_payload,
    create_listing_payload,
    create_mi_claim_payload,
    create_net_sheet_payload,
    create_offer_payload,
    file_dispute_payload,
    file_document_payload,
    file_extension_request_payload,
    issue_approval_letter_payload,
    lien_demand_payload,
    lien_response_payload,
    mi_decision_payload,
    order_valuation_payload,
    package_decision_payload,
    record_value_payload,
    review_document_payload,
    servicer_decision_payload,
)
from .test_users import TEST_USERS, make_bpo_vendor_headers, make_junior_lien_holder_headers

NEG = TEST_USERS["negotiator_headers"]
AGENT = TEST_USERS["listing_agent_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]
ANALYST2 = TEST_USERS["second_analyst_headers"]
HOLDER = TEST_USERS["junior_lien_holder_headers"]
UNDERWRITER = TEST_USERS["mi_underwriter_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Tier 0: primitives ───────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Drive the logical clock. Returns the body carrying the new current_utc."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def create_vendor(**overrides) -> dict:
    return get_success_data(
        api_client.create_bpo_vendor(create_bpo_vendor_payload(**overrides), ADMIN)
    )


def create_case(**overrides) -> dict:
    return get_success_data(api_client.create_case(create_case_payload(**overrides), NEG))


def create_package(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_hardship_package(
            case_id, create_hardship_package_payload(**overrides), NEG
        )
    )


def file_document(package_id: str, doc_type: str, **overrides) -> dict:
    return get_success_data(
        api_client.file_document(package_id, file_document_payload(doc_type, **overrides), NEG)
    )


def review_document(document_id: str, outcome: str, **overrides) -> dict:
    return get_success_data(
        api_client.review_document(
            document_id, review_document_payload(outcome, **overrides), ANALYST
        )
    )


def create_listing(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_listing(case_id, create_listing_payload(**overrides), AGENT)
    )


def create_offer(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_offer(case_id, create_offer_payload(**overrides), AGENT)
    )


def submit_offer(offer_id: str) -> dict:
    return get_success_data(api_client.submit_offer(offer_id, NEG))


def counter_offer(offer_id: str, counter_price_cents: int, note: str = None) -> dict:
    payload = servicer_decision_payload("COUNTER", counter_price_cents=counter_price_cents)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.servicer_decision_on_offer(offer_id, payload, ANALYST))


def reject_offer(offer_id: str, note: str = None) -> dict:
    payload = servicer_decision_payload("REJECT")
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.servicer_decision_on_offer(offer_id, payload, ANALYST))


def revise_offer(offer_id: str, offer_price_cents: int) -> dict:
    return get_success_data(
        api_client.revise_offer(offer_id, {"offer_price_cents": offer_price_cents}, AGENT)
    )


def offer_version(offer_id: str) -> int:
    """Read the offer's current version — the value an OCC net-sheet writer echoes."""
    return get_success_data(api_client.get_offer(offer_id, NEG))["version"]


def case_version(case_id: str) -> int:
    """Read the case's current version — the value an OCC letter writer echoes."""
    return get_success_data(api_client.get_case(case_id, ANALYST))["version"]


def prepare_net_sheet(offer_id: str, variant: str, **overrides) -> dict:
    """Prepare a settlement sheet, reading the offer's current version first."""
    payload = create_net_sheet_payload(variant, offer_version(offer_id), **overrides)
    return get_success_data(api_client.create_net_sheet(offer_id, payload, NEG))


def order_valuation(case_id: str, vendor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.order_valuation(
            case_id, order_valuation_payload(vendor_id, **overrides), ANALYST
        )
    )


def record_value(valuation_id: str, vendor_id: str, value_cents: int) -> dict:
    return get_success_data(
        api_client.record_valuation_value(
            valuation_id, record_value_payload(value_cents), make_bpo_vendor_headers(vendor_id)
        )
    )


def file_dispute(valuation_id, claimed_value_cents, comparable_count, headers=None, **overrides):
    return get_success_data(
        api_client.file_dispute(
            valuation_id,
            file_dispute_payload(claimed_value_cents, comparable_count, **overrides),
            headers or ANALYST2,
        )
    )


def adjudicate_dispute(dispute_id: str, resolution: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_dispute(
            dispute_id, adjudicate_payload(resolution, **overrides), headers or ANALYST2
        )
    )


def create_lien(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_junior_lien(case_id, create_junior_lien_payload(**overrides), NEG)
    )


def send_lien_demand(lien_id: str, demand_cents: int = None) -> dict:
    amount = TEST_DEFAULTS["LIEN_DEMAND_CENTS"] if demand_cents is None else demand_cents
    return get_success_data(
        api_client.send_lien_demand(lien_id, lien_demand_payload(amount), NEG)
    )


def respond_to_lien(lien_id: str, outcome: str, holder_user_id: str = None, **overrides) -> dict:
    holder_headers = (
        HOLDER if holder_user_id is None else make_junior_lien_holder_headers(holder_user_id)
    )
    return get_success_data(
        api_client.respond_to_lien(lien_id, lien_response_payload(outcome, **overrides), holder_headers)
    )


def create_mi_claim(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_mi_claim(case_id, create_mi_claim_payload(**overrides), NEG)
    )


def decide_mi_claim(mi_claim_id: str, outcome: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_mi_claim(mi_claim_id, mi_decision_payload(outcome, **overrides), UNDERWRITER)
    )


def issue_letter(case_id: str, offer_id: str, headers=None, **overrides) -> dict:
    """Issue an approval letter, reading the case's current version first."""
    payload = issue_approval_letter_payload(offer_id, case_version(case_id), **overrides)
    return get_success_data(
        api_client.issue_approval_letter(case_id, payload, headers or ANALYST)
    )


def file_extension(letter_id: str, requested_days: int, **overrides) -> dict:
    return get_success_data(
        api_client.file_extension_request(
            letter_id, file_extension_request_payload(requested_days, **overrides), NEG
        )
    )


def decide_extension(extension_id: str, outcome: str, headers=None) -> dict:
    return get_success_data(
        api_client.decide_extension_request(extension_id, {"outcome": outcome}, headers or ANALYST2)
    )


# ─── Tier 1: documentation and package progression ────

def file_required_documents(package_id: str, issued_on: str = None, overrides_by_type=None) -> dict:
    """File one document of each of the four required kinds. Returns {doc_type: document}."""
    issued = issued_on or TEST_DEFAULTS["DOC_ISSUED_ON"]
    overrides_by_type = overrides_by_type or {}
    documents = {}
    for doc_type in REQUIRED_DOCUMENT_TYPES:
        extra = dict(overrides_by_type.get(doc_type, {}))
        extra.setdefault("issued_on", issued)
        documents[doc_type] = file_document(package_id, doc_type, **extra)
    return documents


def verify_all_documents(documents: dict) -> dict:
    """Verify every filed document. Returns {doc_type: refreshed document}."""
    return {
        doc_type: review_document(document["id"], "VERIFY")
        for doc_type, document in documents.items()
    }


def setup_package_with_documents(case=None, package_overrides=None, issued_on=None,
                                 doc_overrides=None, verify=True, clock=CLOCK_LISTED):
    """Case + package + the four required documents, optionally all verified.

    Returns (case, package, documents).
    """
    if case is None:
        if clock:
            set_clock(clock)
        case = create_case()
    package = create_package(case["id"], **(package_overrides or {}))
    documents = file_required_documents(
        package["id"], issued_on=issued_on, overrides_by_type=doc_overrides
    )
    if verify:
        documents = verify_all_documents(documents)
    package = get_success_data(api_client.get_hardship_package(package["id"], NEG))
    return case, package, documents


def setup_submitted_package(**kwargs):
    """Case + package with all four required documents VERIFIED, package SUBMITTED."""
    case, package, documents = setup_package_with_documents(**kwargs)
    package = get_success_data(api_client.submit_hardship_package(package["id"], NEG))
    return case, package, documents


def setup_accepted_package(**kwargs):
    """Case + package accepted by the servicer, so the case reads MARKETED."""
    case, package, documents = setup_submitted_package(**kwargs)
    package = get_success_data(
        api_client.decide_hardship_package(package["id"], package_decision_payload("ACCEPT"), ANALYST)
    )
    case = get_success_data(api_client.get_case(case["id"], NEG))
    return case, package, documents


# ─── Tier 2: marketing and offers ─────────────────────

def setup_marketed_case(listing_overrides=None, **kwargs):
    """Accepted package + an ACTIVE listing whose window opens 2026-08-05.

    Returns dict(case, package, documents, listing).
    """
    case, package, documents = setup_accepted_package(**kwargs)
    listing = create_listing(case["id"], **(listing_overrides or {}))
    return {"case": case, "package": package, "documents": documents, "listing": listing}


def setup_case_with_draft_offer(clock_at=CLOCK_DOM_19, offer_overrides=None, **kwargs):
    """Marketed case + a DRAFT offer, with the clock advanced past the marketing period.

    Returns dict(case, package, documents, listing, offer).
    """
    scenario = setup_marketed_case(**kwargs)
    if clock_at:
        set_clock(clock_at)
    scenario["offer"] = create_offer(scenario["case"]["id"], **(offer_overrides or {}))
    return scenario


def setup_case_with_submitted_offer(**kwargs):
    """Marketed case + an offer already SUBMITTED to the servicer."""
    scenario = setup_case_with_draft_offer(**kwargs)
    scenario["offer"] = submit_offer(scenario["offer"]["id"])
    scenario["case"] = get_success_data(api_client.get_case(scenario["case"]["id"], NEG))
    return scenario


def setup_countered_offer(counter_price_cents=25_400_000, **kwargs):
    """Marketed case + an offer the servicer has countered."""
    scenario = setup_case_with_submitted_offer(**kwargs)
    scenario["offer"] = counter_offer(scenario["offer"]["id"], counter_price_cents)
    return scenario


def setup_case_after_two_rejected_offers(**kwargs):
    """Two offers submitted and rejected in turn, so the case carries
    failed_offer_count 2, price_reduction_required true, the package
    REVALIDATION_REQUIRED and documentation_status DOC_STALE.

    Returns dict(case, package, documents, listing, offer, second_offer).
    """
    scenario = setup_case_with_submitted_offer(**kwargs)
    scenario["offer"] = reject_offer(scenario["offer"]["id"])
    second = create_offer(
        scenario["case"]["id"],
        buyer_name="Second Buyer",
        offer_price_cents=24_300_000,
    )
    submit_offer(second["id"])
    scenario["second_offer"] = reject_offer(second["id"])
    scenario["case"] = get_success_data(api_client.get_case(scenario["case"]["id"], NEG))
    scenario["package"] = get_success_data(
        api_client.get_hardship_package(scenario["package"]["id"], NEG)
    )
    return scenario


def run_counter_revise_rounds(offer_id: str, rounds):
    """Walk the SUBMITTED -> COUNTERED -> REVISED -> SUBMITTED loop.

    `rounds` is a list of (counter_price_cents, revised_price_cents) pairs. The
    offer is left REVISED after the last pair; each completed pair re-submits.
    """
    for index, (counter_price, revised_price) in enumerate(rounds):
        counter_offer(offer_id, counter_price)
        revise_offer(offer_id, revised_price)
        if index < len(rounds) - 1:
            submit_offer(offer_id)
    return get_success_data(api_client.get_offer(offer_id, NEG))


# ─── Tier 3: valuations and disputes ──────────────────

def setup_recorded_valuation(case=None, vendor=None, value_cents=None,
                             clock=None, case_overrides=None, vendor_overrides=None,
                             valuation_overrides=None):
    """Vendor + case + one valuation with a recorded opinion of value.

    Returns dict(vendor, case, valuation).
    """
    if clock:
        set_clock(clock)
    if vendor is None:
        vendor = create_vendor(**(vendor_overrides or {}))
    if case is None:
        case = create_case(**(case_overrides or {}))
    valuation = order_valuation(case["id"], vendor["id"], **(valuation_overrides or {}))
    valuation = record_value(
        valuation["id"],
        vendor["id"],
        TEST_DEFAULTS["VALUATION_VALUE_CENTS"] if value_cents is None else value_cents,
    )
    case = get_success_data(api_client.get_case(case["id"], NEG))
    return {"vendor": vendor, "case": case, "valuation": valuation}


def setup_open_dispute(claimed_value_cents=27_000_000, comparable_count=4,
                       filer_headers=None, **kwargs):
    """A recorded valuation with one OPEN dispute filed against it by an analyst
    other than the one who ordered it.

    Returns dict(vendor, case, valuation, dispute).
    """
    scenario = setup_recorded_valuation(**kwargs)
    scenario["dispute"] = file_dispute(
        scenario["valuation"]["id"], claimed_value_cents, comparable_count,
        headers=filer_headers,
    )
    scenario["valuation"] = get_success_data(
        api_client.get_valuation(scenario["valuation"]["id"], ANALYST)
    )
    return scenario


# ─── Tier 4: junior liens and mortgage insurance ──────

def setup_case_with_lien(case=None, lien_overrides=None, stage="IDENTIFIED",
                         demand_cents=None, contribution_cents=None, clock=CLOCK_LISTED):
    """Case + one junior lien walked to `stage`.

    stage is one of IDENTIFIED, DEMAND_SENT, NEGOTIATING, APPROVED, REFUSED.
    Returns (case, lien).
    """
    if case is None:
        if clock:
            set_clock(clock)
        case = create_case()
    lien = create_lien(case["id"], **(lien_overrides or {}))
    if stage != "IDENTIFIED":
        lien = send_lien_demand(lien["id"], demand_cents)
    if stage == "NEGOTIATING":
        lien = respond_to_lien(lien["id"], "NEGOTIATE", holder_user_id=lien["holder_user_id"])
    elif stage == "APPROVED":
        amount = (
            TEST_DEFAULTS["LIEN_CONTRIBUTION_CENTS"]
            if contribution_cents is None else contribution_cents
        )
        lien = respond_to_lien(
            lien["id"], "APPROVE", holder_user_id=lien["holder_user_id"],
            contribution_cents=amount,
        )
    elif stage == "REFUSED":
        lien = respond_to_lien(lien["id"], "REFUSE", holder_user_id=lien["holder_user_id"])
    case = get_success_data(api_client.get_case(case["id"], NEG))
    return case, lien


def setup_case_with_mi_claim(case=None, outcome=None, contribution_cents=None,
                             contribution_form="CASH", clock=CLOCK_LISTED):
    """Case + one MI claim, optionally decided. Returns (case, mi_claim)."""
    if case is None:
        if clock:
            set_clock(clock)
        case = create_case()
    claim = create_mi_claim(case["id"])
    if outcome == "APPROVE":
        amount = (
            TEST_DEFAULTS["MI_CONTRIBUTION_CENTS"]
            if contribution_cents is None else contribution_cents
        )
        claim = decide_mi_claim(
            claim["id"], "APPROVE",
            required_contribution_cents=amount, contribution_form=contribution_form,
        )
    elif outcome in ("DECLINE", "NOT_REQUIRED"):
        claim = decide_mi_claim(claim["id"], outcome)
    case = get_success_data(api_client.get_case(case["id"], NEG))
    return case, claim


# ─── Tier 5: the full approval chain ──────────────────

def setup_ready_for_issuance(
    case_overrides=None,
    package_overrides=None,
    listing_overrides=None,
    offer_overrides=None,
    with_valuation=True,
    valuation_value=None,
    lien_stage="APPROVED",
    lien_overrides=None,
    mi_outcome="APPROVE",
    mi_contribution_cents=None,
    net_sheet_variant="FINAL",
    net_sheet_overrides=None,
    lien_response_after_net_sheet=False,
    clock_at_offer=CLOCK_DOM_19,
):
    """Everything an approval letter needs, stopping short of issuing one.

    Walks: clock -> vendor -> case -> package accepted -> listing -> valuation
    recorded -> junior lien -> MI claim -> clock forward -> offer submitted ->
    settlement sheet. Every stage is switchable so negative tests can knock out
    exactly one precondition.

    Returns dict(vendor, case, package, documents, listing, valuation, lien,
    mi_claim, offer, net_sheet).
    """
    set_clock(CLOCK_LISTED)
    vendor = create_vendor() if with_valuation else None

    case, package, documents = setup_accepted_package(
        case=create_case(**(case_overrides or {})),
        package_overrides=package_overrides,
    )
    listing = create_listing(case["id"], **(listing_overrides or {}))

    valuation = None
    if with_valuation:
        valuation = order_valuation(case["id"], vendor["id"])
        valuation = record_value(
            valuation["id"], vendor["id"],
            TEST_DEFAULTS["VALUATION_VALUE_CENTS"] if valuation_value is None else valuation_value,
        )

    lien = None
    if lien_stage is not None:
        lien = create_lien(case["id"], **(lien_overrides or {}))
        if lien_stage != "IDENTIFIED":
            lien = send_lien_demand(lien["id"])
        if not lien_response_after_net_sheet:
            lien = _advance_lien(lien, lien_stage)

    mi_claim = None
    if mi_outcome is not None:
        _, mi_claim = setup_case_with_mi_claim(
            case=case, outcome=None if mi_outcome == "PENDING" else mi_outcome,
            contribution_cents=mi_contribution_cents, clock=None,
        )

    if clock_at_offer:
        set_clock(clock_at_offer)
    offer = create_offer(case["id"], **(offer_overrides or {}))
    offer = submit_offer(offer["id"])

    net_sheet = None
    if net_sheet_variant is not None:
        net_sheet = prepare_net_sheet(
            offer["id"], net_sheet_variant, **(net_sheet_overrides or {})
        )

    if lien is not None and lien_response_after_net_sheet:
        lien = _advance_lien(lien, lien_stage)
        if net_sheet is not None:
            net_sheet = _refresh_net_sheet(offer["id"], net_sheet["id"])

    case = get_success_data(api_client.get_case(case["id"], ANALYST))
    offer = get_success_data(api_client.get_offer(offer["id"], NEG))
    return {
        "vendor": vendor,
        "case": case,
        "package": package,
        "documents": documents,
        "listing": listing,
        "valuation": valuation,
        "lien": lien,
        "mi_claim": mi_claim,
        "offer": offer,
        "net_sheet": net_sheet,
    }


def _advance_lien(lien: dict, stage: str) -> dict:
    if stage == "NEGOTIATING":
        return respond_to_lien(lien["id"], "NEGOTIATE", holder_user_id=lien["holder_user_id"])
    if stage == "APPROVED":
        return respond_to_lien(
            lien["id"], "APPROVE", holder_user_id=lien["holder_user_id"],
            contribution_cents=TEST_DEFAULTS["LIEN_CONTRIBUTION_CENTS"],
        )
    if stage == "REFUSED":
        return respond_to_lien(lien["id"], "REFUSE", holder_user_id=lien["holder_user_id"])
    return lien


def _refresh_net_sheet(offer_id: str, net_sheet_id: str) -> dict:
    sheets, _ = _list_net_sheets(offer_id)
    for sheet in sheets:
        if sheet["id"] == net_sheet_id:
            return sheet
    return None


def _list_net_sheets(offer_id: str, params=None):
    response = api_client.list_offer_net_sheets(offer_id, NEG, params=params)
    return get_success_data(response), response.json().get("meta", {})


def setup_full_approval_chain(letter_overrides=None, **kwargs):
    """The complete chain through an ACTIVE approval letter.

    Returns the `setup_ready_for_issuance` dict plus `letter`, with the case and
    offer re-read after issuance.
    """
    scenario = setup_ready_for_issuance(**kwargs)
    scenario["letter"] = issue_letter(
        scenario["case"]["id"], scenario["offer"]["id"], **(letter_overrides or {})
    )
    scenario["case"] = get_success_data(api_client.get_case(scenario["case"]["id"], ANALYST))
    scenario["offer"] = get_success_data(api_client.get_offer(scenario["offer"]["id"], NEG))
    return scenario


def setup_letter_with_extension_request(requested_days=20, **kwargs):
    """The full chain plus one REQUESTED extension request against the letter."""
    scenario = setup_full_approval_chain(**kwargs)
    scenario["extension"] = file_extension(scenario["letter"]["id"], requested_days)
    return scenario
