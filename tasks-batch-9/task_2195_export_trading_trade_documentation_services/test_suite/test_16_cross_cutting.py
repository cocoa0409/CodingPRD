"""The five optimistic-concurrency fields, the four-link cascade and the pins."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    OPS_ALICE,
    REVIEWER_BOB,
    ApiErrorId,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

Json = Dict[str, Any]

BLADE_LINE = [
    {
        "line_no": 1,
        "goods_description": "stone cutting blades",
        "hs_code": "820221",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]


def _amended_credit(api) -> Json:
    """A credit amended in place after an AMEND recommendation."""
    ctx = fx.order_with_lines(
        api,
        buyer_overrides={
            "legal_name": "Genoa Marble Import Srl",
            "country_code": "IT",
            "credit_rating": "A",
        },
        order_overrides={
            "incoterm_named_place": "Port of Norfolk",
            "destination_country_code": "IT",
            "destination_zone": "ZONE_2",
        },
        lines=BLADE_LINE,
    )
    ctx = fx.captured_credit(
        api,
        ctx,
        lc_number="LC-CORNER-8301",
        issuing_bank_swift="UNCRITMM",
        tolerance_pct=5.00,
        expiry_date="2026-12-31T00:00:00Z",
        latest_shipment_date="2026-09-20T00:00:00Z",
    )
    ctx = fx.opened_terms_review(api, ctx)
    ctx["review_one_id"] = ctx["review_id"]
    ctx["finding"] = fx.data(
        api.raise_terms_finding(
            ctx["review_id"],
            f.terms_finding_payload(
                code="AMOUNT_MISMATCH",
                severity="MAJOR",
                clause_ref="AMOUNT",
                detail="credit amount is short of the order value",
            ),
            REVIEWER_BOB,
        )
    )
    ctx["review_one"] = validate_success(
        api.submit_terms_review(
            ctx["review_id"], {"recommendation": "AMEND"}, REVIEWER_BOB
        ),
        200,
    )
    before = fx.read_credit(api, ctx["lc_id"])
    ctx["version_before_amendment"] = before["version"]
    ctx["status_before_amendment"] = before["status"]
    ctx["credit"] = validate_success(
        api.amend_credit(
            ctx["lc_id"],
            {
                "expected_letter_of_credit_version": before["version"],
                "amount_usd": 30000.00,
            },
            OPS_ALICE,
        ),
        200,
    )
    return ctx


class TestReviewOnAnAmendedCreditRefusesTheStalePin:
    def test_the_review_reopens_only_against_the_post_amendment_version(self, api):
        """PRD §2.6: "Opening a terms review (`POST /letters-of-credit/{lc_id}/reviews`)
        requires `expected_letter_of_credit_version` to equal the target credit's
        current `version`."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_lc_review_stale_credit_after_an_in_place_amendment
        """
        ctx = _amended_credit(api)

        assert ctx["status_before_amendment"] == "AMENDMENT_REQUESTED"
        assert ctx["review_one"]["status"] == "SUBMITTED"
        assert ctx["credit"]["amendment_round"] == 1
        assert ctx["credit"]["status"] == "RECEIVED"
        assert ctx["credit"]["max_drawable_usd"] == approx_money(31500.00)
        assert ctx["credit"]["version"] == ctx["version_before_amendment"] + 1

        validate_error(
            api.open_terms_review(
                ctx["lc_id"],
                {
                    "expected_letter_of_credit_version": ctx["version_before_amendment"]
                },
                REVIEWER_BOB,
            ),
            ApiErrorId.ERR_STALE_LC_VERSION.value,
            412,
        )

        fresh = fx.credit_version(api, ctx["lc_id"])
        assert fresh == ctx["credit"]["version"]

        reopened = validate_success(
            api.open_terms_review(
                ctx["lc_id"],
                {"expected_letter_of_credit_version": fresh},
                REVIEWER_BOB,
            ),
            201,
        )
        assert reopened["status"] == "DRAFTING"

        reviews, meta = validate_paginated(
            api.list_terms_reviews(
                REVIEWER_BOB,
                {"letter_of_credit_id": ctx["lc_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2
        assert reviews[0]["id"] == ctx["review_one_id"]
        assert reviews[0]["status"] == "SUPERSEDED"

        assert fx.data(api.get_finding(ctx["finding"]["id"], REVIEWER_BOB))[
            "cure_status"
        ] == "CURED"


# ---------------------------------------------------------------------------
# The amendment field itself, probed on the second round
# ---------------------------------------------------------------------------

RESIN_LINE = [
    {
        "line_no": 1,
        "goods_description": "resin drums",
        "hs_code": "390940",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

ANTWERP_POLICY = {
    "policy_number": "POL-CORNER-8401",
    "credit_limit_usd": 80000.00,
    "insured_pct": 90.00,
    "deductible_usd": 500.00,
    "effective_from": "2026-07-01T00:00:00Z",
    "effective_to": "2026-12-31T00:00:00Z",
}


def _credit_after_one_amendment(api) -> Json:
    """An accepted credit amended once and then driven back to AMENDMENT_REQUESTED."""
    ctx = fx.order_with_lines(
        api,
        buyer_overrides={
            "legal_name": "Antwerp Chemical Trading NV",
            "country_code": "BE",
            "credit_rating": "AA",
        },
        order_overrides={
            "incoterm": "CFR",
            "incoterm_named_place": "Antwerp",
            "destination_country_code": "BE",
            "destination_zone": "ZONE_2",
            "ship_by_date": "2026-10-31T00:00:00Z",
        },
        lines=RESIN_LINE,
    )
    ctx["policy"] = fx.create_policy(api, ctx["buyer_id"], **ANTWERP_POLICY)
    ctx["policy_id"] = ctx["policy"]["id"]
    ctx = fx.accepted_credit(
        api,
        ctx,
        lc_number="LC-CORNER-8401",
        issuing_bank_swift="GEBABEBB",
        tolerance_pct=5.00,
        expiry_date="2026-12-31T00:00:00Z",
        latest_shipment_date="2026-09-20T00:00:00Z",
    )
    assert ctx["credit"]["status"] == "ACCEPTED"
    assert_order_dimensions(ctx["order"], settlement="LC_ACCEPTED")

    ctx["amendment_one"] = validate_success(
        api.amend_credit(
            ctx["lc_id"],
            {
                "expected_letter_of_credit_version": ctx["credit"]["version"],
                "amount_usd": 30000.00,
            },
            OPS_ALICE,
        ),
        200,
    )
    ctx = fx.opened_terms_review(api, ctx)
    fx.data(
        api.raise_terms_finding(
            ctx["review_id"],
            f.terms_finding_payload(
                code="LATEST_SHIPMENT_UNWORKABLE",
                severity="MAJOR",
                clause_ref="LATEST_SHIPMENT",
                detail="latest shipment date precedes the achievable sailing",
            ),
            REVIEWER_BOB,
        )
    )
    ctx["review_two"] = validate_success(
        api.submit_terms_review(
            ctx["review_id"], {"recommendation": "AMEND"}, REVIEWER_BOB
        ),
        200,
    )
    ctx["credit"] = fx.read_credit(api, ctx["lc_id"])
    return ctx


class TestSecondAmendmentRefusesTheVersionOfTheFirst:
    def test_a_value_two_writes_behind_cannot_apply_the_second_amendment(self, api):
        """PRD §2.6: "Applying an amendment
        (`POST /letters-of-credit/{lc_id}/amendments`) likewise requires
        `expected_letter_of_credit_version` to equal the credit's current `version`,
        and a mismatch is rejected with `ERR_STALE_LC_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_lc_amendment_stale_credit_on_the_second_amendment_round
        """
        ctx = _credit_after_one_amendment(api)

        assert ctx["amendment_one"]["amendment_round"] == 1
        assert ctx["review_two"]["status"] == "SUBMITTED"
        assert ctx["credit"]["status"] == "AMENDMENT_REQUESTED"

        validate_error(
            api.amend_credit(
                ctx["lc_id"],
                {
                    "expected_letter_of_credit_version": ctx["amendment_one"]["version"],
                    "latest_shipment_date": "2026-10-15T00:00:00Z",
                },
                OPS_ALICE,
            ),
            ApiErrorId.ERR_STALE_LC_VERSION.value,
            412,
        )

        amendment_two = validate_success(
            api.amend_credit(
                ctx["lc_id"],
                {
                    "expected_letter_of_credit_version": ctx["credit"]["version"],
                    "latest_shipment_date": "2026-10-15T00:00:00Z",
                },
                OPS_ALICE,
            ),
            200,
        )
        assert amendment_two["amendment_round"] == 2
        assert amendment_two["status"] == "RECEIVED"
        assert amendment_two["latest_shipment_date"].startswith("2026-10-15")

        assert fx.read_credit(api, ctx["lc_id"])["amendment_round"] == 2

        policy = fx.read_policy(api, ctx["policy_id"])
        assert policy["utilized_usd"] == approx_money(0.00)
        assert policy["available_limit_usd"] == approx_money(80000.00)
        assert policy["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# The sailing field, probed across a capacity release
# ---------------------------------------------------------------------------

CLAMP_LINE = [
    {
        "line_no": 1,
        "goods_description": "hull plate clamps",
        "hs_code": "732690",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

BUSAN_SAILING = {
    "carrier_scac": "HDMU",
    "vessel_name": "MV Busan Fitter",
    "voyage_no": "CD-8501",
    "port_of_discharge": "KRPUS",
    "capacity_weight_kg": 2000.000,
}


class TestRebookingAfterACancelDemandsTheTwiceBumpedSailing:
    def test_the_version_the_first_booking_saw_is_two_writes_behind(self, api):
        """PRD §2.6: "Booking freight (`POST /freight-bookings`) requires
        `expected_vessel_sailing_version` to equal the target sailing's current
        `version`, and a mismatch is rejected with `ERR_STALE_SAILING_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_booking_stale_sailing_after_a_cancel_released_capacity
        """
        ctx = fx.booked_order(
            api,
            sailing_overrides=BUSAN_SAILING,
            base=fx.cleared_order(
                api,
                buyer_overrides={
                    "legal_name": "Busan Shipfitting Co",
                    "country_code": "KR",
                    "credit_rating": "A",
                },
                order_overrides={
                    "destination_country_code": "KR",
                    "destination_zone": "ZONE_2",
                },
                lines=CLAMP_LINE,
            ),
        )
        version_at_creation = ctx["sailing"]["version"]
        version_after_booking = fx.sailing_version(api, ctx["sailing_id"])
        assert version_after_booking == version_at_creation + 1
        assert_order_dimensions(ctx["order"], fulfillment="BOOKED")

        cancelled = validate_success(
            api.cancel_booking(
                ctx["booking_id"],
                {"cancel_reason": "buyer deferred the shipment window"},
                OPS_ALICE,
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), fulfillment="COMPLIANCE_CLEARED"
        )

        validate_error(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"], ctx["sailing_id"], version_after_booking
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_STALE_SAILING_VERSION.value,
            412,
        )

        released = fx.read_sailing(api, ctx["sailing_id"])
        assert released["version"] == version_at_creation + 2
        assert released["booked_weight_kg"] == approx_weight(0.000)
        assert released["status"] == "OPEN"

        rebooked = validate_success(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"], ctx["sailing_id"], released["version"]
                ),
                OPS_ALICE,
            ),
            201,
        )
        assert rebooked["status"] == "BOOKED"
        assert fx.read_sailing(api, ctx["sailing_id"])["booked_weight_kg"] == (
            approx_weight(1200.000)
        )

        _, meta = validate_paginated(
            api.list_bookings(
                OPS_ALICE,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# The order field, probed across an unrelated document issue
# ---------------------------------------------------------------------------

SAWMILL_LINE = [
    {
        "line_no": 1,
        "goods_description": "sawmill blades",
        "hs_code": "820231",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

TALLINN_SAILING = {
    "carrier_scac": "MSCU",
    "vessel_name": "MV Baltic Pine",
    "voyage_no": "CD-8601",
    "port_of_discharge": "EETLL",
}


class TestLodgingRefusesAnOrderVersionOneDocumentBehind:
    def test_a_certificate_issued_after_the_read_invalidates_the_pin(self, api):
        """PRD §2.6: "Lodging a presentation (`POST /document-presentations`) requires
        `expected_export_order_version` to equal the order's current `version`, and a
        mismatch is rejected with `ERR_STALE_ORDER_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_presentation_stale_order_after_a_later_document_issue
        """
        ctx = fx.full_tender(
            api,
            buyer_overrides={
                "legal_name": "Tallinn Timber Buyers OU",
                "country_code": "EE",
                "credit_rating": "AA",
            },
            order_overrides={
                "destination_country_code": "EE",
                "destination_zone": "ZONE_2",
            },
            lines=SAWMILL_LINE,
            sailing_overrides=TALLINN_SAILING,
            credit_overrides={
                "lc_number": "LC-CORNER-8601",
                "issuing_bank_swift": "EEUHEE2X",
            },
        )
        stale_version = fx.order_version(api, ctx["order_id"])

        certificate = fx.generate_and_issue(
            api, ctx["order_id"], "CERTIFICATE_OF_ORIGIN"
        )
        assert certificate["status"] == "ISSUED"
        fresh_version = fx.order_version(api, ctx["order_id"])
        assert fresh_version == stale_version + 1

        tender = [ctx["invoice_id"], ctx["packing_list_id"], ctx["bill_of_lading_id"]]
        validate_error(
            api.lodge_presentation(
                f.presentation_payload(
                    ctx["lc_id"], ctx["order_id"], tender, stale_version
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_STALE_ORDER_VERSION.value,
            412,
        )
        _, empty = validate_paginated(
            api.list_presentations(OPS_ALICE, {"limit": 10, "offset": 0})
        )
        assert empty["total_count"] == 0

        presentation = validate_success(
            api.lodge_presentation(
                f.presentation_payload(
                    ctx["lc_id"], ctx["order_id"], tender, fresh_version
                ),
                OPS_ALICE,
            ),
            201,
        )
        assert presentation["status"] == "PRESENTED"
        assert presentation["presentation_round"] == 1

        links = fx.presentation_links(api, presentation["id"])
        assert len(links) == 3
        assert {link["link_status"] for link in links} == {"ACTIVE"}
        assert {link["linked_in_round"] for link in links} == {1}
        assert {link["trade_document_id"] for link in links} == set(tender)


# ---------------------------------------------------------------------------
# The policy field, probed across the acceptance charge
# ---------------------------------------------------------------------------

LOOM_LINE = [
    {
        "line_no": 1,
        "goods_description": "textile loom parts",
        "hs_code": "844859",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

KARACHI_POLICY = {
    "policy_number": "POL-CORNER-8701",
    "credit_limit_usd": 40000.00,
    "insured_pct": 90.00,
    "deductible_usd": 500.00,
    "effective_from": "2026-07-01T00:00:00Z",
    "effective_to": "2026-12-31T00:00:00Z",
}

KARACHI_SAILING = {
    "carrier_scac": "ONEY",
    "vessel_name": "MV Indus Trader",
    "voyage_no": "CD-8701",
    "port_of_discharge": "PKKHI",
    # PRD §3.5: the sailing must serve the order's destination_zone, and this order is
    # prepared for ZONE_3.
    "destination_zone": "ZONE_3",
}


def _dishonoured_insured_order(api) -> Json:
    """A dishonoured, policy-charged order with an OPEN non-payment dispute."""
    ctx = fx.cleared_order(
        api,
        buyer_overrides={
            "legal_name": "Karachi Industrial Supply Pvt",
            "country_code": "PK",
            "credit_rating": "BBB",
        },
        order_overrides={
            "destination_country_code": "PK",
            "destination_zone": "ZONE_3",
        },
        lines=LOOM_LINE,
    )
    ctx["policy"] = fx.create_policy(api, ctx["buyer_id"], **KARACHI_POLICY)
    ctx["policy_id"] = ctx["policy"]["id"]
    ctx["policy_version_at_creation"] = ctx["policy"]["version"]

    ctx = fx.booked_order(api, sailing_overrides=KARACHI_SAILING, base=ctx)
    ctx = fx.confirmed_booking(api, ctx)
    ctx = fx.shipped_order(api, ctx)
    ctx = fx.accepted_credit(
        api,
        ctx,
        lc_number="LC-CORNER-8701",
        issuing_bank_swift="HABBPKKA",
        latest_shipment_date="2026-09-15T00:00:00Z",
    )
    ctx = fx.lodged_presentation(api, ctx)
    ctx = fx.examined_presentation(api, ctx, [])
    ctx["presentation"] = validate_success(
        api.dishonour_presentation(
            ctx["presentation_id"],
            {"refusal_reason": "issuing bank refused: applicant insolvent"},
            FINANCE_FRANK,
        ),
        200,
    )
    ctx["dispute"] = fx.data(
        api.open_dispute(
            f.dispute_payload(
                ctx["order_id"],
                dispute_type="NON_PAYMENT",
                claimed_amount_usd=25000.00,
            ),
            FINANCE_FRANK,
        )
    )
    ctx["dispute_id"] = ctx["dispute"]["id"]
    ctx["order"] = fx.read_order(api, ctx["order_id"])
    return ctx


class TestClaimFilingRefusesThePreChargePolicyVersion:
    def test_the_acceptance_charge_moved_the_headroom_the_claim_was_sized_against(
        self, api
    ):
        """PRD §2.6: "Filing an insurance claim
        (`POST /credit-insurance-policies/{policy_id}/claims`) requires
        `expected_credit_insurance_policy_version` to equal the policy's current
        `version`, and a mismatch is rejected with `ERR_STALE_POLICY_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_claim_stale_policy_version_bumped_by_the_acceptance_charge
        """
        ctx = _dishonoured_insured_order(api)

        assert_order_dimensions(ctx["order"], settlement="DISHONORED")
        assert ctx["order"]["insured_exposure_usd"] == approx_money(25000.00)
        assert ctx["dispute"]["status"] == "OPEN"
        assert ctx["dispute"]["credit_insurance_policy_id"] is None

        charged = fx.read_policy(api, ctx["policy_id"])
        assert charged["utilized_usd"] == approx_money(25000.00)
        assert charged["available_limit_usd"] == approx_money(15000.00)
        assert charged["version"] > ctx["policy_version_at_creation"]

        validate_error(
            api.file_claim(
                ctx["policy_id"],
                f.claim_payload(
                    ctx["dispute_id"], ctx["policy_version_at_creation"]
                ),
                FINANCE_FRANK,
            ),
            ApiErrorId.ERR_STALE_POLICY_VERSION.value,
            412,
        )
        assert fx.read_policy(api, ctx["policy_id"])["status"] == "ACTIVE"
        assert fx.data(api.get_dispute(ctx["dispute_id"], FINANCE_FRANK))[
            "credit_insurance_policy_id"
        ] is None

        validate_success(
            api.file_claim(
                ctx["policy_id"],
                f.claim_payload(ctx["dispute_id"], charged["version"]),
                FINANCE_FRANK,
            ),
            200,
        )
        after = fx.read_policy(api, ctx["policy_id"])
        assert after["utilized_usd"] == approx_money(25000.00)
        assert after["version"] == charged["version"] + 1

        linked = fx.data(api.get_dispute(ctx["dispute_id"], FINANCE_FRANK))
        assert linked["credit_insurance_policy_id"] == ctx["policy_id"]
        assert linked["status"] == "OPEN"
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="CLAIM_FILED"
        )


# ---------------------------------------------------------------------------
# One flag, four links
# ---------------------------------------------------------------------------

APPLIANCE_LINE = [
    {
        "line_no": 1,
        "goods_description": "encryption appliances",
        "hs_code": "851762",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

DUBAI_LICENSE = {
    "license_number": "BIS-CORNER-8801",
    "licensed_value_usd": 25000.00,
    "valid_from": "2026-07-01T00:00:00Z",
    "valid_to": "2026-12-31T00:00:00Z",
}

DUBAI_SAILING = {
    "carrier_scac": "CMDU",
    "vessel_name": "MV Gulf Corner",
    "voyage_no": "CD-8801",
    "port_of_discharge": "AEJEA",
    "destination_zone": "ZONE_3",
    "capacity_weight_kg": 1200.000,
}


def _booked_licensed_order_plus_a_draft(api) -> Json:
    """A BOOKED order that has saturated a sailing and a licence, plus a DRAFT sibling."""
    ctx = fx.licensed_cleared_order(
        api,
        eccn="5A992",
        license_overrides=DUBAI_LICENSE,
        buyer_overrides={
            "legal_name": "Dubai Network Devices FZE",
            "country_code": "AE",
            "credit_rating": "A",
        },
        order_overrides={
            "destination_country_code": "AE",
            "destination_zone": "ZONE_3",
        },
        lines=APPLIANCE_LINE,
    )
    ctx = fx.booked_order(api, sailing_overrides=DUBAI_SAILING, base=ctx)
    ctx["screening_before"] = fx.data(
        api.get_screening(ctx["screening_id"], COMPLIANCE_CARL)
    )
    ctx["order_version_before"] = ctx["order"]["version"]
    ctx["draft_order"] = fx.create_order(
        api,
        ctx["buyer_id"],
        destination_country_code="AE",
        destination_zone="ZONE_3",
        incoterm_named_place="Port of Long Beach",
    )
    return ctx


class TestOneRestrictedPartyFlagUnwindsFourLinksAtOnce:
    def test_the_blocked_order_releases_its_booking_capacity_licence_and_clearance(
        self, api
    ):
        """PRD §3.1: "For each order that just moved, every freight booking of that
        order whose `status` is `BOOKED` or `CONFIRMED` moves to `CANCELLED` with
        `cancel_reason` set to the literal string `'RESTRICTED_PARTY_CASCADE'`."

        Design: Corner/cross_cutting_complexity_layers/corner_restricted_party_flag_unwinds_four_cascade_links_in_one_write
        """
        ctx = _booked_licensed_order_plus_a_draft(api)

        saturated_sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert saturated_sailing["booked_weight_kg"] == approx_weight(1200.000)
        assert saturated_sailing["status"] == "FULL"
        exhausted = fx.data(api.get_license(ctx["license_id"], COMPLIANCE_CARL))
        assert exhausted["consumed_value_usd"] == approx_money(25000.00)
        assert exhausted["remaining_value_usd"] == approx_money(0.00)
        assert exhausted["status"] == "EXHAUSTED"
        assert ctx["screening_before"]["status"] == "CLEARED"
        assert ctx["screening_before"]["cleared_at"] is not None

        flagged = validate_success(
            api.patch_restricted_party_flag(
                ctx["buyer_id"],
                {
                    "restricted_party_flag": True,
                    "restricted_party_reason": "named on a denied-party list",
                },
                COMPLIANCE_CARL,
            ),
            200,
        )
        assert flagged["restricted_party_flag"] is True

        blocked = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(blocked, fulfillment="COMPLIANCE_BLOCKED")
        assert blocked["version"] == ctx["order_version_before"] + 1
        assert blocked["licensed_value_allocated_usd"] == approx_money(0.00)

        untouched = fx.read_order(api, ctx["draft_order"]["id"])
        assert_order_dimensions(untouched, fulfillment="DRAFT")
        assert untouched["version"] == ctx["draft_order"]["version"]

        booking = fx.data(api.get_booking(ctx["booking_id"], OPS_ALICE))
        assert booking["status"] == "CANCELLED"
        assert booking["cancel_reason"] == "RESTRICTED_PARTY_CASCADE"

        released_sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert released_sailing["booked_weight_kg"] == approx_weight(0.000)
        assert released_sailing["status"] == "OPEN"

        released_license = fx.data(api.get_license(ctx["license_id"], COMPLIANCE_CARL))
        assert released_license["consumed_value_usd"] == approx_money(0.00)
        assert released_license["remaining_value_usd"] == approx_money(25000.00)
        assert released_license["status"] == "ACTIVE"

        screening = fx.data(api.get_screening(ctx["screening_id"], COMPLIANCE_CARL))
        assert screening["status"] == "INITIATED"
        assert screening["ruleset_version"] == (
            ctx["screening_before"]["ruleset_version"] + 1
        )
        assert screening["cleared_at"] is None


# ---------------------------------------------------------------------------
# The usance branch of the pricing pair
# ---------------------------------------------------------------------------

SPINDLE_LINE = [
    {
        "line_no": 1,
        "goods_description": "CNC spindle assemblies",
        "hs_code": "845811",
        "quantity": 800.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 8000.000,
        "gross_weight_kg": 9600.000,
        "package_count": 80,
    }
]

YOKOHAMA_POLICY = {
    "policy_number": "POL-CORNER-8901",
    "credit_limit_usd": 250000.00,
    "insured_pct": 90.00,
    "deductible_usd": 1000.00,
    "effective_from": "2026-07-01T00:00:00Z",
    "effective_to": "2026-12-31T00:00:00Z",
}

YOKOHAMA_SAILING = {
    "carrier_scac": "ONEY",
    "vessel_name": "MV Kanto Corner",
    "voyage_no": "CD-8901",
    "port_of_discharge": "JPYOK",
    "destination_zone": "ZONE_3",
}

USANCE_TERMS = {
    "lc_number": "LC-CORNER-8901",
    "issuing_bank_swift": "BOTKJPJT",
    "amount_usd": 200000.00,
    "tolerance_pct": 5.00,
    "availability": "USANCE",
    "usance_days": 90,
    "latest_shipment_date": "2026-09-15T00:00:00Z",
    "required_document_types": ["COMMERCIAL_INVOICE", "PACKING_LIST"],
}


def _usance_drawing(api) -> Json:
    """A complying tender priced under a 90-day usance credit."""
    ctx = fx.cleared_order(
        api,
        buyer_overrides={
            "legal_name": "Yokohama Machine Tool KK",
            "country_code": "JP",
            "credit_rating": "AA",
        },
        order_overrides={
            "destination_country_code": "JP",
            "destination_zone": "ZONE_3",
        },
        lines=SPINDLE_LINE,
    )
    ctx["policy"] = fx.create_policy(api, ctx["buyer_id"], **YOKOHAMA_POLICY)
    ctx["policy_id"] = ctx["policy"]["id"]
    ctx = fx.booked_order(
        api,
        sailing_overrides=YOKOHAMA_SAILING,
        booking_overrides={"booked_weight_kg": 9600.000},
        base=ctx,
    )
    ctx = fx.confirmed_booking(api, ctx)
    ctx = fx.shipped_order(api, ctx)
    ctx = fx.accepted_credit(api, ctx, **USANCE_TERMS)
    ctx = fx.lodged_presentation(api, ctx)
    ctx = fx.examined_presentation(api, ctx, [])
    return ctx


class TestTheUsanceBranchDeductsBothFeeAndDiscount:
    def test_a_ninety_day_tenor_prices_the_drawing_below_the_sight_figure(self, api):
        """PRD §3.7: "The usance discount is exactly 0.00 when `availability` is
        `SIGHT`, and otherwise gross multiplied by 4.75 percent multiplied by
        `usance_days` divided by a 360-day basis, rounded to two decimal places; the
        day fraction is not rounded before the multiplication."

        Design: Corner/cross_cutting_complexity_layers/corner_dual_variant_usance_negotiation_deducts_a_discount_the_sight_branch_never_charges
        """
        ctx = _usance_drawing(api)

        assert ctx["credit"]["max_drawable_usd"] == approx_money(210000.00)
        assert ctx["credit"]["min_drawable_usd"] == approx_money(190000.00)
        assert fx.read_policy(api, ctx["policy_id"])["utilized_usd"] == (
            approx_money(200000.00)
        )

        presentation = ctx["presentation"]
        assert presentation["status"] == "COMPLIED"
        assert presentation["presented_amount_usd"] == approx_money(200000.00)
        assert presentation["negotiable_amount_usd"] == approx_money(197375.00)

        settled = validate_success(
            api.settle_presentation(
                ctx["presentation_id"],
                {
                    "received_amount_usd": 197375.00,
                    "value_date": "2026-08-02T00:00:00Z",
                },
                FINANCE_FRANK,
            ),
            200,
        )
        assert settled["status"] == "HONOURED"
        assert settled["received_amount_usd"] == approx_money(197375.00)

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "UTILISED"
        assert credit["drawn_amount_usd"] == approx_money(197375.00)

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="CLOSED", settlement="PAID")
        assert order["outstanding_receivable_usd"] == approx_money(2625.00)
        assert order["insured_exposure_usd"] == approx_money(0.00)

        policy = fx.read_policy(api, ctx["policy_id"])
        assert policy["utilized_usd"] == approx_money(0.00)
        assert policy["available_limit_usd"] == approx_money(250000.00)
        assert policy["status"] == "ACTIVE"

        buyer = fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))
        assert buyer["aggregate_exposure_usd"] == approx_money(0.00)
        assert buyer["open_order_count"] == 0


# ---------------------------------------------------------------------------
# The pin follows the revision chain
# ---------------------------------------------------------------------------

CORK_LINE = [
    {
        "line_no": 1,
        "goods_description": "cork press dies",
        "hs_code": "820790",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]


class TestEachRevisionCarriesItsOwnPinnedOrderVersion:
    def test_the_second_revision_pins_the_version_the_first_could_no_longer_reach(
        self, api
    ):
        """PRD §3.5: "The predecessor moves to `SUPERSEDED` and a new row of the same
        `doc_type` is created with `revision` incremented by one, `status` `DRAFT`,
        `supersedes_document_id` pointing at the predecessor, and `pinned_order_version`
        set to the order's **current** `version`."

        Design: Corner/cross_cutting_complexity_layers/corner_pinned_source_version_travels_with_each_document_revision
        """
        ctx = fx.cleared_order(
            api,
            buyer_overrides={
                "legal_name": "Lisbon Cork Importers Lda",
                "country_code": "PT",
                "credit_rating": "A",
            },
            order_overrides={
                "incoterm_named_place": "Port of Charleston",
                "destination_country_code": "PT",
                "destination_zone": "ZONE_2",
            },
            lines=CORK_LINE,
        )
        order_version_at_generation = fx.order_version(api, ctx["order_id"])

        revision_one = validate_success(
            api.generate_document(
                f.document_payload(ctx["order_id"], "COMMERCIAL_INVOICE"), OPS_ALICE
            ),
            201,
        )
        assert revision_one["revision"] == 1
        assert revision_one["supersedes_document_id"] is None
        assert revision_one["pinned_order_version"] == order_version_at_generation

        certificate = fx.generate_and_issue(
            api, ctx["order_id"], "CERTIFICATE_OF_ORIGIN"
        )
        assert certificate["status"] == "ISSUED"
        assert fx.order_version(api, ctx["order_id"]) == (
            order_version_at_generation + 1
        )

        validate_error(
            api.issue_document(revision_one["id"], OPS_ALICE),
            ApiErrorId.ERR_DOCUMENT_STALE_SOURCE.value,
            409,
        )

        revision_two = validate_success(
            api.regenerate_document(
                revision_one["id"],
                {"reason": "the order moved on before the invoice was issued"},
                OPS_ALICE,
            ),
            201,
        )
        assert revision_two["revision"] == 2
        assert revision_two["supersedes_document_id"] == revision_one["id"]
        assert revision_two["pinned_order_version"] == (
            revision_one["pinned_order_version"] + 1
        )
        assert revision_two["status"] == "DRAFT"

        predecessor = fx.data(api.get_document(revision_one["id"], OPS_ALICE))
        assert predecessor["status"] == "SUPERSEDED"

        issued = validate_success(api.issue_document(revision_two["id"], OPS_ALICE), 200)
        assert issued["status"] == "ISSUED"
        assert issued["declared_total_usd"] == approx_money(25000.00)

        children, meta = validate_paginated(
            api.list_documents(
                OPS_ALICE,
                {
                    "supersedes_document_id": revision_one["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert children[0]["id"] == revision_two["id"]
        assert children[0]["revision"] == 2
