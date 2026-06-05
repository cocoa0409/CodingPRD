"""Corner-design coverage — cross_cutting section (optimistic concurrency)."""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    register_provider,
    create_included_damages,
    create_proposed_damages,
    include_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    create_offer,
    accept_offer,
    get_case,
    get_case_version,
    get_disbursement_for_case,
    ApiErrorId,
    api_client,
    accept_offer_payload,
    release_disbursement_payload,
    make_managing_partner_headers,
    setup_active_case_with_reviewed_records,
    setup_case_in_negotiation_with_offer,
)


# ─── stale_case_version_on_settle_accept ────────────────────────────


def test_accept_with_stale_expected_case_version_returns_412(api):
    """PRD §2.8: "The accept action on a settlement offer is the first: the
    request body must carry an `expected_case_version` field, and that
    integer must equal the parent case's current `version` at the moment
    the server processes the write. If another writer has advanced the
    case since the client last read it — say, a paralegal included a new
    damages line item that bumped `included_damages_total_cents` and
    incremented `Case.version` between the partner reading the case and
    the partner clicking accept — the request is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412), so the partner cannot accept an
    offer based on a damages picture that has already changed."

    Design: Corner/cross_cutting/stale_case_version_on_settle_accept
    """
    from test_helpers import TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    client, case_neg, provider, offer = setup_case_in_negotiation_with_offer(
        offer_amount_cents=4_000_000, by_party="CARRIER",
    )
    # Observe the current Case.version (partner's "stale" snapshot).
    case_v_observed = get_case_version(case_neg["id"])
    # Another writer mutates the case — include a new damages item bumping
    # included_damages_total_cents and Case.version.
    item2 = create_proposed_damages(case_neg["id"], "LOST_WAGES", 300_000)
    include_damages(item2["id"])
    # Now attempt accept with the now-stale expected_case_version.
    res = api_client.accept_offer(
        offer["id"], accept_offer_payload(case_v_observed),
        make_managing_partner_headers(),
    )
    validate_error(res, ApiErrorId.ERR_STALE_CASE_VERSION.value)
    # State on both sides is untouched.
    offer_after = validate_success(
        api.get_offer(offer["id"], TEST_USERS["attorney_headers"]), 200
    )
    case_after = get_case(case_neg["id"])
    assert offer_after["status"] == "PENDING"
    assert case_after["status"] == "IN_NEGOTIATION"


# ─── stale_case_version_on_disbursement_release ─────────────────────


def test_release_with_stale_expected_case_version_returns_412(api):
    """PRD §2.8: "The release action on a disbursement is the second OCC
    path: it likewise requires `expected_case_version` on the body, and a
    mismatch with the case's current `version` is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412) for the same reason — a late lien
    adjustment that bumps the case version must force a re-read before the
    check is cut."

    Design: Corner/cross_cutting/stale_case_version_on_disbursement_release
    """
    from test_helpers import TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    client, case, provider, mrr = setup_active_case_with_reviewed_records()
    create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
    dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                               drafter_user_id="drafter-ds")
    send_demand_letter(dl["id"], partner_user_id="partner-ds")
    create_lien(case["id"], provider["id"], 500_000)
    offer = create_offer(case["id"], 6_000_000, "CARRIER")
    case_v = get_case_version(case["id"])
    accept_offer(offer["id"], case_v, partner_user_id="partner-ds")
    disb = get_disbursement_for_case(case["id"])
    # Current case_version post-settle.
    case_v_current = get_case_version(case["id"])
    # Use a stale expected_case_version (one less than current).
    res = api_client.release_disbursement(
        disb["id"], release_disbursement_payload(case_v_current - 1),
        make_managing_partner_headers("partner-ds"),
    )
    validate_error(res, ApiErrorId.ERR_STALE_CASE_VERSION.value)
    disb_after = validate_success(
        api.get_disbursement(disb["id"], TEST_USERS["attorney_headers"]), 200
    )
    assert disb_after["status"] == "PENDING"
