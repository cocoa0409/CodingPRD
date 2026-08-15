"""Rebate/tax-credit dossiers: gating, OCC docs patching, qualification math, payout."""
from datetime import datetime

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, make_contractor_headers, TEST_USERS, ApiErrorId,
    make_contractor, make_system_rating, create_draft_order, add_line,
    submit_order, ship_order, deliver_order, set_clock,
    setup_delivered_rating_order, setup_docs_complete_rebate, create_dossier,
)

ADMIN = TEST_USERS["distributor_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestRebateQualificationPinnedMath:
    """PREMIUM system, installed cost 500000: federal credit is
    min(200000, round_half_up(500000 * 0.30)) == 150000. The indoor coil is
    priced at 0 so the installed cost is 500000 under any reasonable
    component-pricing reading of the order line."""

    def _setup_qualified_dossier(self):
        set_clock("2026-08-10T00:00:00Z")
        ctx = setup_delivered_rating_order(seer2=17.0, eer2=12.5,
                                           ou_price_cents=500_000,
                                           iu_price_cents=0,
                                           family_code="FAM-Q")
        install_date = ctx["order"]["submitted_at"]
        rebate = create_dossier(
            ctx, docs=["AHRI_CERTIFICATE", "INVOICE", "LOAD_CALC", "PERMIT"],
            program_type="FEDERAL_TAX_CREDIT", install_date=install_date)
        rebate = get_success_data(api_client.submit_rebate(
            rebate["id"], make_contractor_headers(ctx["contractor"]["id"])))
        ctx["rebate"] = rebate
        return ctx

    def test_qualify_applies_thirty_percent_cap_below_tier_amount(self, api):
        """PRD §3.8: "Qualifying (`QUALIFY`) moves `DOCS_COMPLETE` → `QUALIFIED` and fixes the incentive under a pinned four-step evaluation. First, the installed cost is the sum of `line_total_cents` across the order's lines referencing this rating — already net of any line discounts. Second, the efficiency tier amount is read from the rating's class: $2,000 (200,000 cents) for `PREMIUM`, $1,000 (100,000 cents) for `HIGH`, and nothing for `STANDARD`. Third, the program lane applies its cap: a `FEDERAL_TAX_CREDIT` pays the lesser of the tier amount and thirty percent of the installed cost — the thirty-percent term rounded half-up to whole cents before the comparison — while a `UTILITY_REBATE` pays the flat tier amount but nothing when the class is `STANDARD`."

        Design: Difficulty/combinatorial_formula/rebate_qualification_circular_order_pinned
        """
        ctx = self._setup_qualified_dossier()
        assert ctx["rebate"]["status"] == "DOCS_COMPLETE", "setup: all four docs attached"
        qualified = validate_success(api_client.rebate_decision(
            ctx["rebate"]["id"], {"action": "QUALIFY"}, OFFICER), 200)
        assert qualified["status"] == "QUALIFIED"
        assert qualified["qualified_amount_cents"] == 150_000, (
            f"min(200000, round_half_up(500000 * 0.30)) == 150000, "
            f"got {qualified['qualified_amount_cents']}")

    def test_premium_rating_fields_and_docs_complete_fast_path(self, api):
        """PRD §3.2: "First, `efficiency_class`: a rating with `seer2` at least 17.0 and `eer2` at least 12.0 is `PREMIUM`; otherwise one with `seer2` at least 15.2 and `eer2` at least 11.7 is `HIGH`; anything else is `STANDARD`."
        PRD §3.2: "Second, `tax_credit_eligible` is true precisely when the class is `PREMIUM`, or when the class is `HIGH` and a non-null `hspf2` of at least 8.1 is on record."
        PRD §3.8: "A dossier submitted with all four documents already attached flows `DRAFT` → `SUBMITTED` → `DOCS_COMPLETE` inside the same request."
        PRD §3.8: "Acceptance stamps `submitted_at` and sets `decision_deadline` forty-five days later."

        Design: Difficulty/combinatorial_formula/rebate_qualification_circular_order_pinned
        """
        ctx = self._setup_qualified_dossier()
        rating = get_success_data(api_client.get_ahri_rating(ctx["rating"]["id"], ADMIN))
        assert rating["efficiency_class"] == "PREMIUM"
        assert rating["tax_credit_eligible"] is True
        rebate = ctx["rebate"]
        assert rebate["status"] == "DOCS_COMPLETE", (
            "all four documents at submit flow straight to DOCS_COMPLETE")
        submitted_at = datetime.fromisoformat(rebate["submitted_at"].replace("Z", "+00:00"))
        deadline = datetime.fromisoformat(rebate["decision_deadline"].replace("Z", "+00:00"))
        assert (deadline - submitted_at).days == 45


class TestRebateSubmitOrderGate:
    def _setup_shipped_dossier(self):
        set_clock("2026-08-05T00:00:00Z")
        contractor = make_contractor(license_number="LIC-014")
        rating, ou, iu = make_system_rating("FAM-M", seer2=17.0, eer2=12.5)
        order = create_draft_order(contractor)
        add_line(order["id"], contractor, ahri_rating_id=rating["id"], quantity=1)
        order = submit_order(order["id"], contractor)
        ship_order(order["id"])
        rebate = create_dossier(
            {"contractor": contractor, "order": order, "rating": rating},
            docs=["AHRI_CERTIFICATE", "INVOICE"],
            install_date=order["submitted_at"])
        return contractor, order, rebate

    def test_submit_rejected_while_order_only_shipped(self, api):
        """PRD §3.8: "The referenced order must be `DELIVERED`; the referenced rating must be `ACTIVE`; for the `FEDERAL_TAX_CREDIT` lane the rating must be `tax_credit_eligible`; and the checklist must already contain at least `AHRI_CERTIFICATE` and `INVOICE`."
        PRD §3.8: "A dossier failing the order- or rating-state gates is rejected with `ERR_INVALID_STATE` (409); one failing the consistency or document requirements with `ERR_REBATE_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/rebate_submit_requires_order_delivered
        """
        contractor, order, rebate = self._setup_shipped_dossier()
        assert get_success_data(api_client.get_order(order["id"], ADMIN))["status"] == "SHIPPED"
        res = api_client.submit_rebate(
            rebate["id"], make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        dossier = get_success_data(api_client.get_rebate_submission(rebate["id"], ADMIN))
        assert dossier["status"] == "DRAFT"

    def test_submit_succeeds_once_order_delivered(self, api):
        """PRD §3.8: "The referenced order must be `DELIVERED`; the referenced rating must be `ACTIVE`; for the `FEDERAL_TAX_CREDIT` lane the rating must be `tax_credit_eligible`; and the checklist must already contain at least `AHRI_CERTIFICATE` and `INVOICE`."
        PRD §3.8: "Acceptance stamps `submitted_at` and sets `decision_deadline` forty-five days later."

        Design: Difficulty/cross_entity_state_dependency/rebate_submit_requires_order_delivered
        """
        contractor, order, rebate = self._setup_shipped_dossier()
        deliver_order(order["id"])
        submitted = validate_success(api_client.submit_rebate(
            rebate["id"], make_contractor_headers(contractor["id"])), 200)
        assert submitted["status"] == "SUBMITTED", (
            "only two of four documents attached, so the dossier stops at SUBMITTED")
        assert submitted.get("submitted_at"), "submitted_at must be stamped"


def test_qualify_from_draft_rejected(api):
    """PRD §3.8: "Qualifying (`QUALIFY`) moves `DOCS_COMPLETE` → `QUALIFIED` and fixes the incentive under a pinned four-step evaluation."
    PRD §2.8: "5. **From-state legality** — the target resource must be in a legal from-state for the requested transition; failures yield `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/rebate_qualify_from_draft_rejected
    """
    ctx = setup_delivered_rating_order(family_code="FAM-I")
    rebate = create_dossier(ctx, install_date=ctx["order"]["submitted_at"])
    assert rebate["status"] == "DRAFT", "setup: dossier opens in DRAFT"
    res = api_client.rebate_decision(rebate["id"], {"action": "QUALIFY"}, OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_rebate_rating_not_on_order_rejected(api):
    """PRD §3.8: "Consistency is enforced at both creation and submission: the referenced rating must appear on a line of the referenced order, and the `install_date` must be no earlier than the order's `submitted_at` and no later than the logical clock; mismatches are rejected with `ERR_REBATE_MISMATCH` (422)."

    Design: Corner/validations/rebate_reference_to_absent_rating_line_mismatch
    """
    contractor = make_contractor(license_number="LIC-C402")
    rating1, ou, iu = make_system_rating("FAM-A1", seer2=17.0, eer2=12.5)
    rating2 = validate_success(api_client.create_ahri_rating(
        {"ahri_reference_number": "AHRI-M402B", "outdoor_unit_id": ou["id"],
         "indoor_unit_id": iu["id"], "seer2": 16.0, "eer2": 12.0}, ADMIN), 201)
    order = create_draft_order(contractor)
    add_line(order["id"], contractor, ahri_rating_id=rating1["id"], quantity=1)
    order = submit_order(order["id"], contractor)
    ship_order(order["id"])
    order = deliver_order(order["id"])
    res = api_client.create_rebate_submission(
        {"contractor_id": contractor["id"], "order_id": order["id"],
         "ahri_rating_id": rating2["id"], "program_type": "UTILITY_REBATE",
         "homeowner_name": "M", "install_address": "9 Pine",
         "install_date": order["submitted_at"]},
        make_contractor_headers(contractor["id"]))
    validate_error(res, ApiErrorId.ERR_REBATE_MISMATCH)


def test_rebate_patch_stale_version_rejected(api):
    """PRD §2.6: "Patching a rebate dossier's document checklist — the endpoint `PATCH /rebate-submissions/{id}` — requires `expected_rebate_version`. Because the checklist is cumulative, a writer working from an outdated checklist snapshot would silently drop documents another writer already attached; a mismatch with the dossier's current `version` is therefore rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.8: "The patch is guarded by the optimistic-concurrency rule of §2.6 via `expected_rebate_version`, and the checklist is **cumulative**: the payload list is merged into the stored checklist as a union, so documents accumulate and none are ever removed by a patch."

    Design: Corner/endpoints/rebate_patch_occ_stale_version_conflict
    """
    ctx = setup_delivered_rating_order(family_code="FAM-X7")
    contractor = ctx["contractor"]
    headers = make_contractor_headers(contractor["id"])
    rebate = create_dossier(ctx, docs=["AHRI_CERTIFICATE"],
                            install_date=ctx["order"]["submitted_at"])
    stale_version = rebate["version"]
    patched = validate_success(api_client.patch_rebate_submission(
        rebate["id"], {"expected_rebate_version": stale_version,
                       "docs": ["AHRI_CERTIFICATE", "INVOICE"]}, headers), 200)
    assert set(patched["docs"]) == {"AHRI_CERTIFICATE", "INVOICE"}, (
        "the checklist is cumulative: the payload list is union-merged")
    assert patched["version"] != stale_version, "setup: first patch must bump the version"

    res = api_client.patch_rebate_submission(
        rebate["id"], {"expected_rebate_version": stale_version,
                       "docs": ["AHRI_CERTIFICATE", "INVOICE", "LOAD_CALC"]}, headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    dossier = get_success_data(api_client.get_rebate_submission(rebate["id"], ADMIN))
    assert set(dossier["docs"]) == {"AHRI_CERTIFICATE", "INVOICE"}, (
        "the rejected patch must not have attached LOAD_CALC")


def test_rebate_pay_after_deadline(api):
    """PRD §3.8: "Payment (`PAY`) is reserved to `DistributorAdmin` and must occur at or before the `decision_deadline`; a payout attempted past the deadline is rejected with `ERR_WINDOW_EXPIRED` (422)."
    PRD §3.8: "A `QUALIFIED` dossier whose deadline passes unpaid transitions to `EXPIRED` at the next read or transition — its `qualified_amount_cents` remains on record but is no longer payable."

    Design: Corner/errors/rebate_pay_after_deadline_window_expired
    """
    set_clock("2026-08-02T00:00:00Z")
    ctx = setup_docs_complete_rebate(family_code="FAM-U4")
    rebate = ctx["rebate"]
    qualified = validate_success(api_client.rebate_decision(
        rebate["id"], {"action": "QUALIFY"}, OFFICER), 200)
    assert qualified["status"] == "QUALIFIED", "setup"
    recorded_amount = qualified["qualified_amount_cents"]

    # decision_deadline is submitted_at + 45 days == 2026-09-16T00:00:00Z
    set_clock("2026-09-17T00:00:00Z")
    res = api_client.rebate_decision(rebate["id"], {"action": "PAY"}, ADMIN)
    validate_error_is_one_of(res, [ApiErrorId.ERR_WINDOW_EXPIRED,
                                   ApiErrorId.ERR_ALREADY_TERMINAL])
    dossier = get_success_data(api_client.get_rebate_submission(rebate["id"], ADMIN))
    assert dossier["status"] == "EXPIRED", (
        "an unpaid QUALIFIED dossier past its decision_deadline reads as EXPIRED")
    assert dossier["qualified_amount_cents"] == recorded_amount, (
        "the qualified amount remains on record after expiry")


def test_contractor_cannot_qualify_rebate(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the targeted endpoint or action is rejected with `ERR_UNAUTHORIZED` (HTTP 403) — for example, a `ContractorUser` attempting to qualify a rebate dossier."
    PRD §2.1: "Symmetrically, a `ComplianceOfficer` qualifies or rejects rebate dossiers but may never pay one; payout is reserved to `DistributorAdmin`."

    Design: Corner/roles/contractor_cannot_qualify_rebate
    """
    ctx = setup_docs_complete_rebate(family_code="FAM-T3")
    rebate = ctx["rebate"]
    assert rebate["status"] == "DOCS_COMPLETE", "setup"
    res = api_client.rebate_decision(
        rebate["id"], {"action": "QUALIFY"},
        make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    dossier = get_success_data(api_client.get_rebate_submission(rebate["id"], ADMIN))
    assert dossier["status"] == "DOCS_COMPLETE"
