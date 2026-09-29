"""The four authorisation gates and the two duty boundaries, in ladder order."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ADMIN_PAT,
    COMPLIANCE_CARL,
    DUAL_DANA_AS_OPS,
    DUAL_DANA_AS_REVIEWER,
    FINANCE_FRANK,
    OPS_ALICE,
    REVIEWER_BOB,
    USER_IDS,
    ApiErrorId,
    approx_weight,
    factories as f,
    fixtures as fx,
    make_buyer_headers,
    make_headers,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

Json = Dict[str, Any]

# --- header shapes that priority 1 must refuse ------------------------------
NO_HEADERS: Dict[str, str] = {}
BLANK_USER_ID = {"X-User-ID": "", "X-User-Role": "ExportOpsCoordinator"}
BLANK_ROLE = {"X-User-ID": "u_admin_pat", "X-User-Role": ""}

# --- fabricated identifiers: none of these ever resolve ---------------------
FAKE_BUYER_ID = "11111111-0000-4000-8000-0000000000a1"
FAKE_LC_ID = "11111111-0000-4000-8000-0000000000b1"
FAKE_ORDER_ID = "11111111-0000-4000-8000-0000000000c1"
FAKE_PRESENTATION_ID = "11111111-0000-4000-8000-0000000000c2"
FAKE_ORDER_ID_2 = "11111111-0000-4000-8000-0000000000c3"
FAKE_BUYER_ID_2 = "11111111-0000-4000-8000-0000000000c4"
FAKE_BUYER_ID_3 = "11111111-0000-4000-8000-0000000000d1"
FAKE_ORDER_ID_3 = "11111111-0000-4000-8000-0000000000d2"

# A body that is defective twice over: an undeclared incoterm and an undeclared
# destination zone, on top of a buyer id that resolves to nothing.
DEFECTIVE_ORDER_BODY = {
    "buyer_id": FAKE_BUYER_ID,
    "incoterm": "FOB_PLUS",
    "incoterm_named_place": "Nowhere",
    "origin_country_code": "US",
    "destination_country_code": "DE",
    "destination_zone": "ZONE_9",
    "invoice_currency": "USD",
    "fx_rate_usd_to_invoice": 1.000000,
    "ship_by_date": "2026-09-30T00:00:00Z",
}


class TestAbsentOrBlankHeadersOutrankEveryBodyDefect:
    def test_three_shapes_of_broken_auth_answer_with_one_code(self, api):
        """PRD §2.1: "If either header is absent or empty, the request is rejected
        with `ERR_MISSING_AUTH_HEADERS` (401)."

        Design: Corner/rbac/corner_absent_or_blank_headers_outrank_every_body_defect_missing_auth_headers
        """
        both_absent = validate_error(
            api.create_order(DEFECTIVE_ORDER_BODY, NO_HEADERS),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            401,
        )
        assert both_absent["error_id"] != ApiErrorId.ERR_VALIDATION.value
        assert both_absent["error_id"] != ApiErrorId.ERR_BUYER_NOT_FOUND.value

        validate_error(
            api.list_credits(BLANK_USER_ID, f.pagination(10, 0)),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            401,
        )
        blank_role = validate_error(
            api.set_clock_raw({"current_utc": "the day after tomorrow"}, BLANK_ROLE),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            401,
        )
        assert blank_role["error_id"] != ApiErrorId.ERR_VALIDATION.value

        orders, meta = validate_paginated(api.list_orders(OPS_ALICE, f.pagination(10, 0)))
        assert orders == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        _, credit_meta = validate_paginated(
            api.list_credits(OPS_ALICE, f.pagination(10, 0))
        )
        assert credit_meta["total_count"] == 0


class TestUnrecognisedRoleIsRejectedBeforePathResolution:
    def test_an_invented_a_lowercased_and_an_abbreviated_role_all_fail_at_401(self, api):
        """PRD §2.1: "If `X-User-Role` carries a value that is not one of the six
        roles below, the rejection is `ERR_UNKNOWN_ROLE` (401)."

        Design: Corner/rbac/corner_unrecognised_role_string_is_rejected_before_path_resolution_invalid_role
        """
        invented = validate_error(
            api.get_credit(FAKE_LC_ID, make_headers("u_ghost_gary", "TradeFinanceWizard")),
            ApiErrorId.ERR_UNKNOWN_ROLE.value,
            401,
        )
        assert invented["error_id"] != ApiErrorId.ERR_LC_NOT_FOUND.value

        lowercased = api.list_orders(
            make_headers("u_ops_alice", "exportopscoordinator"), f.pagination(10, 0)
        )
        validate_error(lowercased, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)

        abbreviated = api.list_disputes(
            make_headers("u_ops_alice", "Buyer"), f.pagination(10, 0)
        )
        validate_error(abbreviated, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)

        assert lowercased.status_code != 403
        assert abbreviated.status_code != 403


class TestRoleGateFiresBeforePathAndBodyExistence:
    def test_four_forbidden_callers_never_see_the_missing_rows_behind_them(self, api):
        """PRD §2.1: "If the role is recognised but is not listed among the authorised
        roles for the endpoint being called (see the table in §4), the rejection is
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/corner_role_gate_fires_before_path_and_body_existence_forbidden
        """
        sailing = fx.create_sailing(
            api,
            carrier_scac="MAEU",
            vessel_name="MV Clock Witness",
            cutoff_at="2026-08-18T00:00:00Z",
            etd="2026-08-21T00:00:00Z",
            eta="2026-09-10T00:00:00Z",
        )

        writes_document = validate_error(
            api.generate_document(
                {"export_order_id": FAKE_ORDER_ID, "doc_type": "COMMERCIAL_INVOICE"},
                COMPLIANCE_CARL,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        assert writes_document["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND.value

        examines = validate_error(
            api.examine_presentation(FAKE_PRESENTATION_ID, {"findings": []}, FINANCE_FRANK),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        assert examines["error_id"] != ApiErrorId.ERR_PRESENTATION_NOT_FOUND.value

        validate_error(
            api.set_clock("2027-01-01T00:00:00Z", REVIEWER_BOB),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        # Had the refused call moved the clock past both instants, step 4 of the
        # sweep would have carried this sailing all the way to DEPARTED.
        unmoved = fx.read_sailing(api, sailing["id"])
        assert unmoved["status"] == "OPEN"
        assert unmoved["version"] == sailing["version"]

        reads_item = validate_error(
            api.get_order(FAKE_ORDER_ID_2, make_buyer_headers(FAKE_BUYER_ID_2)),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        assert reads_item["error_id"] != ApiErrorId.ERR_BUYER_IDENTITY_NOT_FOUND.value
        assert reads_item["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND.value


class TestBuyerIdentityMustResolveToABuyerRow:
    def test_an_unknown_uuid_and_a_foreign_key_from_another_family_both_fail(self, api):
        """PRD §2.1: "If a caller claims `ForeignBuyer` but `X-User-ID` is not the
        `id` of an existing `ForeignBuyer` row, the request is rejected with
        `ERR_BUYER_IDENTITY_NOT_FOUND` (403)."

        Design: Corner/rbac/corner_buyer_identity_must_resolve_to_a_buyer_row_before_scope_forbidden
        """
        buyer = fx.create_buyer(
            api, legal_name="Rotterdam Bulk Handling BV", country_code="NL"
        )
        order = fx.create_order(
            api,
            buyer["id"],
            incoterm="CIF",
            incoterm_named_place="Rotterdam",
            destination_country_code="NL",
            destination_zone="ZONE_2",
        )

        unknown = validate_error(
            api.list_orders(make_buyer_headers(FAKE_BUYER_ID_3), f.pagination(10, 0)),
            ApiErrorId.ERR_BUYER_IDENTITY_NOT_FOUND.value,
            403,
        )
        assert unknown["error_id"] != ApiErrorId.ERR_BUYER_SCOPE_VIOLATION.value

        # A real UUID, but the primary key of an ExportOrder rather than of a buyer.
        validate_error(
            api.list_disputes(make_buyer_headers(order["id"]), f.pagination(10, 0)),
            ApiErrorId.ERR_BUYER_IDENTITY_NOT_FOUND.value,
            403,
        )

        identity_before_body = validate_error(
            api.open_dispute(
                {
                    "export_order_id": FAKE_ORDER_ID_3,
                    "dispute_type": "QUALITY",
                    "claimed_amount_usd": 100.00,
                },
                make_buyer_headers(FAKE_BUYER_ID_3),
            ),
            ApiErrorId.ERR_BUYER_IDENTITY_NOT_FOUND.value,
            403,
        )
        assert identity_before_body["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND.value

        visible, meta = validate_paginated(
            api.list_orders(make_buyer_headers(buyer["id"]), f.pagination(10, 0))
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in visible] == [order["id"]]


# ---------------------------------------------------------------------------
# Ownership: the scope comparison walks the target row back to its order
# ---------------------------------------------------------------------------

COTTON_LINE = [
    {
        "line_no": 1,
        "goods_description": "cotton yarn",
        "hs_code": "520512",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]


def _two_buyers_one_finding(api) -> Json:
    """Buyer A owns a credit under review carrying one MINOR terms finding."""
    ctx = fx.order_with_lines(
        api,
        buyer_overrides={"legal_name": "Alexandria Textiles SAE", "country_code": "EG"},
        order_overrides={
            "incoterm_named_place": "Port of Savannah",
            "destination_country_code": "EG",
            "destination_zone": "ZONE_3",
        },
        lines=COTTON_LINE,
    )
    ctx = fx.captured_credit(
        api,
        ctx,
        lc_number="LC-CORNER-8001",
        issuing_bank_swift="NBEGEGCX",
        tolerance_pct=5.00,
        expiry_date="2026-12-31T00:00:00Z",
        latest_shipment_date="2026-09-20T00:00:00Z",
    )
    ctx = fx.opened_terms_review(api, ctx)
    ctx["finding"] = fx.data(
        api.raise_terms_finding(
            ctx["review_id"],
            f.terms_finding_payload(
                code="PARTIAL_SHIPMENT_BARRED",
                severity="MINOR",
                clause_ref="OTHER",
                detail="partial shipments prohibited without buyer consent",
            ),
            REVIEWER_BOB,
        )
    )
    ctx["finding_id"] = ctx["finding"]["id"]

    intruder = fx.create_buyer(
        api,
        legal_name="Casablanca Fibre SARL",
        country_code="MA",
        credit_rating="BB",
    )
    ctx["intruder_id"] = intruder["id"]
    ctx["intruder_headers"] = make_buyer_headers(intruder["id"])
    ctx["intruder_order"] = fx.create_order(
        api,
        intruder["id"],
        incoterm_named_place="Port of Savannah",
        destination_country_code="MA",
        destination_zone="ZONE_3",
    )
    return ctx


class TestOneBuyerCannotReachAnotherBuyersRows:
    def test_the_intruder_is_refused_on_writes_and_narrowed_on_reads(self, api):
        """PRD §2.1: "If the identity resolves but the targeted resource belongs to a
        different buyer — that is, the `buyer_id` of the `ExportOrder` reached through
        the target resource differs from `X-User-ID` — the rejection is
        `ERR_BUYER_SCOPE_VIOLATION` (403)."

        Design: Corner/rbac/corner_one_buyer_cannot_reach_another_buyers_finding_or_order_forbidden
        """
        ctx = _two_buyers_one_finding(api)

        validate_error(
            api.waive_finding(
                ctx["finding_id"],
                {"buyer_reference": "BR-INTRUDER-0001"},
                ctx["intruder_headers"],
            ),
            ApiErrorId.ERR_BUYER_SCOPE_VIOLATION.value,
            403,
        )
        validate_error(
            api.open_dispute(
                f.dispute_payload(
                    ctx["order_id"], dispute_type="QUALITY", claimed_amount_usd=1000.00
                ),
                ctx["intruder_headers"],
            ),
            ApiErrorId.ERR_BUYER_SCOPE_VIOLATION.value,
            403,
        )

        own, meta = validate_paginated(
            api.list_orders(ctx["intruder_headers"], f.pagination(20, 0))
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in own] == [ctx["intruder_order"]["id"]]

        waived = validate_success(
            api.waive_finding(
                ctx["finding_id"], {"buyer_reference": "BR-OWNER-0001"}, ctx["buyer_headers"]
            ),
            200,
        )
        assert waived["cure_status"] == "WAIVED"
        assert waived["waived_by_buyer_id"] == ctx["buyer_id"]


# ---------------------------------------------------------------------------
# Segregation of duties: the comparison is on the user id, not on the role
# ---------------------------------------------------------------------------

DUAL_DANA_ID = USER_IDS["dual_dana"]


class TestTheCapturerCannotReviewUnderASecondHat:
    def test_a_permitted_role_does_not_launder_the_duty_conflict(self, api):
        """PRD §2.8: "The operator who captured a credit's terms may not review them:
        opening a terms review requires `X-User-ID` to differ from the credit's
        `captured_by_user_id`."

        Design: Corner/rbac/corner_the_person_who_captured_the_credit_cannot_review_it_under_a_second_hat
        """
        buyer = fx.create_buyer(
            api, legal_name="Gdansk Marine Fitting Sp z o o", country_code="PL", credit_rating="A"
        )
        order = fx.create_order(
            api,
            buyer["id"],
            DUAL_DANA_AS_OPS,
            incoterm_named_place="Port of Baltimore",
            destination_country_code="PL",
            destination_zone="ZONE_2",
        )
        credit = validate_success(
            api.capture_credit(
                f.credit_payload(
                    order["id"],
                    lc_number="LC-CORNER-8101",
                    issuing_bank_swift="BPKOPLPW",
                    tolerance_pct=5.00,
                    expiry_date="2026-12-31T00:00:00Z",
                    latest_shipment_date="2026-09-20T00:00:00Z",
                ),
                DUAL_DANA_AS_OPS,
            ),
            201,
        )
        assert credit["captured_by_user_id"] == DUAL_DANA_ID

        validate_error(
            api.open_terms_review(
                credit["id"],
                {"expected_letter_of_credit_version": credit["version"]},
                DUAL_DANA_AS_REVIEWER,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            409,
        )

        review = validate_success(
            api.open_terms_review(
                credit["id"],
                {"expected_letter_of_credit_version": credit["version"]},
                REVIEWER_BOB,
            ),
            201,
        )
        assert review["status"] == "DRAFTING"
        assert review["reviewer_user_id"] == "u_rev_bob"
        assert fx.read_credit(api, credit["id"])["status"] == "UNDER_REVIEW"

        _, meta = validate_paginated(
            api.list_terms_reviews(
                REVIEWER_BOB, {"letter_of_credit_id": credit["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1


SPRAYER_LINE = [
    {
        "line_no": 1,
        "goods_description": "orchard sprayers",
        "hs_code": "842482",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

ANDES_SAILING = {
    "carrier_scac": "HLCU",
    "vessel_name": "MV Andes Corner",
    "voyage_no": "CD-8201",
    "port_of_loading": "USHOU",
    "port_of_discharge": "CLVAP",
    "destination_zone": "ZONE_3",
    "cutoff_at": "2026-08-18T00:00:00Z",
    "etd": "2026-08-21T00:00:00Z",
    "eta": "2026-09-10T00:00:00Z",
    "capacity_weight_kg": 40000.000,
    "tariff_rate_per_1000kg_usd": 300.00,
}


def _tender_prepared_by_two_hands(api) -> Json:
    """The invoice is prepared by one coordinator and the packing list by another."""
    ctx = fx.cleared_order(
        api,
        buyer_overrides={
            "legal_name": "Valparaiso Fruit Exporters SA",
            "country_code": "CL",
            "credit_rating": "A",
        },
        order_overrides={
            "incoterm_named_place": "Port of Houston",
            "destination_country_code": "CL",
            "destination_zone": "ZONE_3",
        },
        lines=SPRAYER_LINE,
        decision_overrides={"eccn": "3A991"},
    )
    ctx = fx.accepted_credit(
        api,
        ctx,
        lc_number="LC-CORNER-8201",
        issuing_bank_swift="BCHICLRM",
        expiry_date="2026-12-31T00:00:00Z",
        latest_shipment_date="2026-09-20T00:00:00Z",
        required_document_types=["COMMERCIAL_INVOICE", "PACKING_LIST"],
    )
    ctx = fx.booked_order(
        api,
        base=ctx,
        sailing_overrides=ANDES_SAILING,
        booking_overrides={"container_type": "LCL"},
    )

    draft = validate_success(
        api.generate_document(f.document_payload(ctx["order_id"]), DUAL_DANA_AS_OPS), 201
    )
    ctx["invoice"] = validate_success(api.issue_document(draft["id"], OPS_ALICE), 200)
    ctx["invoice_id"] = ctx["invoice"]["id"]
    ctx["packing_list"] = fx.generate_and_issue(
        api, ctx["order_id"], "PACKING_LIST", OPS_ALICE
    )
    ctx["packing_list_id"] = ctx["packing_list"]["id"]
    ctx["booking"] = fx.data(api.confirm_booking(ctx["booking_id"], OPS_ALICE))
    ctx = fx.shipped_order(api, ctx)
    ctx = fx.lodged_presentation(
        api, ctx, [ctx["invoice_id"], ctx["packing_list_id"]]
    )
    return ctx


class TestEveryActivePreparerIsBarredFromExamining:
    def test_a_two_preparer_tender_bars_two_users_and_admits_the_terms_reviewer(
        self, api
    ):
        """PRD §2.8: "The operator who generated a tendered document may not examine
        the presentation that contains it: examining a presentation requires
        `X-User-ID` to differ from the `generated_by_user_id` of **every** trade
        document linked to that presentation with `link_status` `ACTIVE`."

        Design: Corner/rbac/corner_no_document_preparer_may_examine_a_presentation_that_carries_its_own_paper
        """
        ctx = _tender_prepared_by_two_hands(api)

        assert ctx["invoice"]["generated_by_user_id"] == DUAL_DANA_ID
        assert ctx["packing_list"]["generated_by_user_id"] == USER_IDS["ops_alice"]

        validate_error(
            api.examine_presentation(
                ctx["presentation_id"], {"findings": []}, DUAL_DANA_AS_REVIEWER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            409,
        )
        validate_error(
            api.examine_presentation(
                ctx["presentation_id"],
                {"findings": []},
                make_reviewer_headers(USER_IDS["ops_alice"]),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            409,
        )

        examined = validate_success(
            api.examine_presentation(ctx["presentation_id"], {"findings": []}, REVIEWER_BOB),
            200,
        )
        assert examined["status"] == "COMPLIED"
        assert examined["open_finding_count"] == 0
        assert examined["examined_by_user_id"] == USER_IDS["rev_bob"]

        links = fx.presentation_links(api, ctx["presentation_id"])
        assert len(links) == 2
        assert all(link["link_status"] == "ACTIVE" for link in links)
        tendered = {link["trade_document_id"] for link in links}
        assert tendered == {ctx["invoice_id"], ctx["packing_list_id"]}
        assert ctx["bill_of_lading_id"] not in tendered


# ---------------------------------------------------------------------------
# The closed six-way ring of exclusive surfaces
# ---------------------------------------------------------------------------

RING_BUYER_ID = "11111111-0000-4000-8000-0000000000e6"
RING_ORDER_BUYER_ID = "11111111-0000-4000-8000-0000000000e7"


class TestEachRoleIsLockedOutOfTheOtherExclusiveSurfaces:
    def test_six_probes_answer_403_and_none_leaks_a_not_found(self, api):
        """PRD §2.11: "The named role appears in the target endpoint's
        authorised-role list, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`
        (403)."

        Design: Corner/rbac/corner_each_role_is_locked_out_of_the_other_five_exclusive_surfaces_forbidden
        """
        forbidden = ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        validate_error(
            api.patch_restricted_party_flag(
                "11111111-0000-4000-8000-0000000000e1",
                {
                    "restricted_party_flag": True,
                    "restricted_party_reason": "attempted by the wrong role",
                },
                OPS_ALICE,
            ),
            forbidden,
            403,
        )

        raises_finding = validate_error(
            api.raise_terms_finding(
                "11111111-0000-4000-8000-0000000000e2",
                f.terms_finding_payload(
                    code="AMOUNT_MISMATCH",
                    severity="MAJOR",
                    clause_ref="AMOUNT",
                    detail="attempted by the wrong role",
                ),
                COMPLIANCE_CARL,
            ),
            forbidden,
            403,
        )
        assert raises_finding["error_id"] != ApiErrorId.ERR_REVIEW_NOT_FOUND.value

        validate_error(
            api.settle_presentation(
                "11111111-0000-4000-8000-0000000000e3",
                {"received_amount_usd": 1000.00, "value_date": "2026-08-05T00:00:00Z"},
                REVIEWER_BOB,
            ),
            forbidden,
            403,
        )
        validate_error(
            api.waive_finding(
                "11111111-0000-4000-8000-0000000000e4",
                {"buyer_reference": "BR-WRONG-ROLE"},
                FINANCE_FRANK,
            ),
            forbidden,
            403,
        )

        buyer_closes = validate_error(
            api.close_dispute(
                "11111111-0000-4000-8000-0000000000e5",
                {"reason": "attempted by the buyer"},
                make_buyer_headers(RING_BUYER_ID),
            ),
            forbidden,
            403,
        )
        assert buyer_closes["error_id"] != ApiErrorId.ERR_BUYER_IDENTITY_NOT_FOUND.value

        admin_creates_order = validate_error(
            api.create_order(
                f.order_payload(
                    RING_ORDER_BUYER_ID,
                    incoterm_named_place="Port of Seattle",
                    destination_country_code="JP",
                    destination_zone="ZONE_3",
                ),
                ADMIN_PAT,
            ),
            forbidden,
            403,
        )
        assert admin_creates_order["error_id"] != ApiErrorId.ERR_BUYER_NOT_FOUND.value

        _, order_meta = validate_paginated(api.list_orders(OPS_ALICE, f.pagination(10, 0)))
        assert order_meta["total_count"] == 0
        _, finding_meta = validate_paginated(
            api.list_findings(REVIEWER_BOB, f.pagination(10, 0))
        )
        assert finding_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# The two co-owned write surfaces and their disjoint peer sets
# ---------------------------------------------------------------------------

PEER_SAILING_ONE = {
    "carrier_scac": "SAFM",
    "vessel_name": "MV Peer One",
    "voyage_no": "CD-9001",
    "port_of_loading": "USNYC",
    "port_of_discharge": "VNHPH",
    "destination_zone": "ZONE_3",
    "cutoff_at": "2026-08-18T00:00:00Z",
    "etd": "2026-08-21T00:00:00Z",
    "eta": "2026-09-25T00:00:00Z",
    "capacity_weight_kg": 30000.000,
    "tariff_rate_per_1000kg_usd": 310.00,
}

PEER_SAILING_TWO = dict(
    PEER_SAILING_ONE,
    vessel_name="MV Peer Two",
    voyage_no="CD-9002",
    port_of_discharge="LKCMB",
    cutoff_at="2026-08-19T00:00:00Z",
    etd="2026-08-22T00:00:00Z",
    eta="2026-09-27T00:00:00Z",
    tariff_rate_per_1000kg_usd=305.00,
)

PEER_SAILING_THREE = dict(
    PEER_SAILING_ONE,
    vessel_name="MV Peer Three",
    voyage_no="CD-9003",
    cutoff_at="2026-08-20T00:00:00Z",
    etd="2026-08-23T00:00:00Z",
    eta="2026-09-29T00:00:00Z",
    tariff_rate_per_1000kg_usd=300.00,
)


class TestSharedSurfacesAdmitEveryDeclaredPeerAndRejectOutsiders:
    def test_the_two_co_owned_surfaces_have_disjoint_peer_sets(self, api):
        """PRD §2.1: "If the role is recognised but is not listed among the authorised
        roles for the endpoint being called (see the table in §4), the rejection is
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/corner_shared_surfaces_admit_every_declared_peer_and_reject_outsiders
        """
        by_compliance = validate_success(
            api.create_buyer(
                f.buyer_payload(legal_name="Haiphong Logistics JSC", country_code="VN"),
                COMPLIANCE_CARL,
            ),
            201,
        )
        by_admin = validate_success(
            api.create_buyer(
                f.buyer_payload(
                    legal_name="Colombo Tea Brokers Ltd",
                    country_code="LK",
                    credit_rating="BB",
                    sanctions_tier="WATCHLIST",
                ),
                ADMIN_PAT,
            ),
            201,
        )
        assert by_compliance["id"] != by_admin["id"]
        assert by_admin["sanctions_tier"] == "WATCHLIST"

        validate_error(
            api.create_buyer(
                f.buyer_payload(
                    legal_name="Ops Should Not Onboard Ltd",
                    country_code="IE",
                    credit_rating="A",
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )

        sailing_by_ops = validate_success(
            api.create_sailing(f.sailing_payload(**PEER_SAILING_ONE), OPS_ALICE), 201
        )
        assert sailing_by_ops["status"] == "OPEN"
        assert sailing_by_ops["booked_weight_kg"] == approx_weight(0.000)

        sailing_by_admin = validate_success(
            api.create_sailing(f.sailing_payload(**PEER_SAILING_TWO), ADMIN_PAT), 201
        )
        assert sailing_by_admin["id"] != sailing_by_ops["id"]
        assert sailing_by_admin["status"] == "OPEN"

        validate_error(
            api.create_sailing(f.sailing_payload(**PEER_SAILING_THREE), COMPLIANCE_CARL),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )

        assert fx.data(api.get_buyer(by_compliance["id"], COMPLIANCE_CARL))[
            "legal_name"
        ] == "Haiphong Logistics JSC"
        assert fx.data(api.get_buyer(by_admin["id"], COMPLIANCE_CARL))[
            "legal_name"
        ] == "Colombo Tea Brokers Ltd"
        assert {
            fx.read_sailing(api, sailing_by_ops["id"])["voyage_no"],
            fx.read_sailing(api, sailing_by_admin["id"])["voyage_no"],
        } == {"CD-9001", "CD-9002"}


# ---------------------------------------------------------------------------
# PlatformAdmin: read-omniscient, write-narrow
# ---------------------------------------------------------------------------

PLATE_SAILING = {
    "carrier_scac": "MAEU",
    "vessel_name": "MV Plate Corner",
    "voyage_no": "CD-9101",
    "port_of_loading": "USCHS",
    "port_of_discharge": "UYMVD",
    "destination_zone": "ZONE_3",
    "cutoff_at": "2026-08-18T00:00:00Z",
    "etd": "2026-08-21T00:00:00Z",
    "eta": "2026-09-12T00:00:00Z",
    "capacity_weight_kg": 25000.000,
    "tariff_rate_per_1000kg_usd": 290.00,
}


class TestPlatformAdminReadsEveryAggregateYetWritesOnlyItsOwn:
    def test_read_omniscience_never_widens_into_write_authority(self, api):
        """PRD §2.1: "If the role is recognised but is not listed among the authorised
        roles for the endpoint being called (see the table in §4), the rejection is
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/corner_platform_admin_reads_every_aggregate_yet_writes_only_its_own_surfaces
        """
        buyer = validate_success(
            api.create_buyer(
                f.buyer_payload(
                    legal_name="Montevideo Wool Traders SA", country_code="UY"
                ),
                ADMIN_PAT,
            ),
            201,
        )
        sailing = validate_success(
            api.create_sailing(f.sailing_payload(**PLATE_SAILING), ADMIN_PAT), 201
        )

        assert fx.data(api.get_buyer(buyer["id"], ADMIN_PAT))[
            "legal_name"
        ] == "Montevideo Wool Traders SA"
        assert fx.data(api.get_sailing(sailing["id"], ADMIN_PAT))["voyage_no"] == "CD-9101"

        empty_collections = (
            api.list_shipment_lines,
            api.list_terms_reviews,
            api.list_licenses,
            api.list_presentation_links,
            api.list_policies,
        )
        for reader in empty_collections:
            rows, meta = validate_paginated(reader(ADMIN_PAT, f.pagination(10, 0)))
            assert rows == []
            assert meta["total_count"] == 0
            assert meta["has_more"] is False
            assert meta["limit"] == 10
            assert meta["offset"] == 0

        generates = validate_error(
            api.generate_document(
                {
                    "export_order_id": "11111111-0000-4000-8000-0000000000f1",
                    "doc_type": "COMMERCIAL_INVOICE",
                },
                ADMIN_PAT,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        assert generates["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND.value

        decides = validate_error(
            api.record_screening_decision(
                "11111111-0000-4000-8000-0000000000f2",
                f.screening_decision_payload(eccn="3A991"),
                ADMIN_PAT,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        assert decides["error_id"] != ApiErrorId.ERR_SCREENING_NOT_FOUND.value
