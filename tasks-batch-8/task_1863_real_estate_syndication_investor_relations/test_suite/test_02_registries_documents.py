"""Investor/property registries, offering and subscription creation defaults,
and subscription document upload semantics."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_investor,
    assert_offering,
    assert_subscription,
    assert_subscription_document,
    get_document,
    make_active_syndication,
    make_draft_subscription,
    make_investor,
    make_open_offering,
    make_property,
    upload_and_review_documents,
    create_document_payload,
    make_investor_headers,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]


class TestInvestorDefaults:
    def test_investor_create_portal_access_defaults_invited(
            self, api, sponsor_operator_headers):
        """PRD §3.1: "A freshly registered investor's `portal_access_status`
        starts at `INVITED`, and their `accreditation_expires_on` is null until
        the first successful accreditation verification stamps it ninety days
        out."

        Design: Corner/entities/investor_create_portal_access_defaults_invited
        """
        resp = api.create_investor(
            {"full_legal_name": "D Inv", "tax_id_last4": "1234",
             "email": "d-inv@example.com", "investor_class": "ACCREDITED"},
            sponsor_operator_headers)
        data = validate_success(resp, 201)
        assert_investor(data)
        assert data["portal_access_status"] == "INVITED"


class TestOfferingDefaults:
    def test_offering_create_aggregates_zero(self, api, sponsor_operator_headers):
        """PRD §3.2: "A new offering is `DRAFT`, with `total_committed_cents`,
        `total_funded_cents`, and `total_distributed_cents` all initialized to
        zero." PRD §3.2 defines the offering's `unreturned_capital_cents` as
        "`total_funded_cents` minus the cumulative return-of-capital already
        paid to limited partners", which is zero on a fresh offering.

        Design: Corner/entities/offering_create_total_committed_funded_distributed_zero
        """
        syn = make_active_syndication(syndication_name="D Syn")
        prop = make_property(property_legal_name="D Prop")
        draft = api.create_offering(syn["id"], {
            "property_id": prop["id"], "offering_name": "D Off",
            "target_raise_cents": 1_000_000, "min_subscription_cents": 10_000,
            "max_non_accredited_count": 35}, sponsor_operator_headers)
        data = validate_success(draft, 201)
        assert_offering(data)
        assert data["status"] == "DRAFT"
        assert data["total_committed_cents"] == 0
        assert data["total_funded_cents"] == 0
        assert data["total_distributed_cents"] == 0
        assert data["unreturned_capital_cents"] == 0


class TestSubscriptionDefaults:
    def test_subscription_create_initializes_computed_fields(
            self, api, sponsor_operator_headers):
        """PRD §3.3: "The draft starts in `DRAFT` with `funded_cents`,
        `accrued_pref_cents`, and `unreturned_capital_cents` all at zero."

        Design: Corner/entities/subscription_create_initializes_computed_fields
        """
        syn = make_active_syndication(syndication_name="CF Syn")
        off = make_open_offering(syn["id"], offering_name="CF Off")
        inv = make_investor(full_legal_name="CF Inv")
        resp = api.create_subscription(syn["id"], off["id"],
                                       {"investor_id": inv["id"],
                                        "committed_cents": 5_000_000},
                                       make_investor_headers(inv["id"]))
        data = validate_success(resp, 201)
        assert_subscription(data)
        assert data["status"] == "DRAFT"
        assert data["funded_cents"] == 0
        assert data["accrued_pref_cents"] == 0
        assert data["unreturned_capital_cents"] == 0


class TestDocumentUpload:
    def test_document_create_pending_review_default(
            self, api, sponsor_operator_headers):
        """PRD §3.3: "Document collection happens against the draft: each
        upload names a `doc_type` — one of `SUBSCRIPTION_AGREEMENT`, `W9`,
        `ACCREDITATION_LETTER`, `ID_PROOF`, or `SUITABILITY_QUESTIONNAIRE` —
        plus a `file_uri` pointing at the stored blob, and the server stamps
        `received_at` and sets `review_status` to `PENDING_REVIEW`."

        Design: Corner/entities/document_create_pending_review_default
        """
        syn = make_active_syndication(syndication_name="Doc Syn")
        off = make_open_offering(syn["id"], offering_name="Doc Off")
        inv = make_investor(full_legal_name="Doc Inv")
        sub = make_draft_subscription(off, inv, 5_000_000, syn["id"])
        resp = api.upload_document(syn["id"], off["id"], sub["id"],
                                   create_document_payload(doc_type="W9"),
                                   make_investor_headers(inv["id"]))
        data = validate_success(resp, 201)
        assert_subscription_document(data)
        assert data["review_status"] == "PENDING_REVIEW"
        assert data["received_at"], "received_at must be stamped by the server"
        assert data.get("reviewed_by") is None, (
            "reviewed_by records the reviewing officer, so it must be null "
            "while the document is still PENDING_REVIEW")

    def test_document_immutable_no_update_endpoint(
            self, api, compliance_officer_headers):
        """PRD §2.4: "Two resource kinds are deliberately lighter:
        `SubscriptionDocument` and `DistributionLine` carry only `id` and
        `created_at`; they have neither `updated_at` nor `version`, since
        documents are immutable once uploaded (their `review_status` flips in
        place via the review workflow) and distribution lines are discarded and
        regenerated rather than edited."

        Design: Corner/entities/document_immutable_no_update_endpoint
        """
        syn = make_active_syndication(syndication_name="ImSyn")
        off = make_open_offering(syn["id"], offering_name="Im Off")
        inv = make_investor(full_legal_name="Im Inv")
        sub = make_draft_subscription(off, inv, 5_000_000, syn["id"])
        docs = upload_and_review_documents(syn["id"], off["id"], sub["id"],
                                           inv["id"], upload_types=("W9",),
                                           accept_types=())
        doc = get_document(syn["id"], off["id"], sub["id"], docs["W9"]["id"])
        # Read via the API as a compliance officer to check the serialized shape.
        resp = api.get_document(syn["id"], off["id"], sub["id"], doc["id"],
                                compliance_officer_headers)
        data = validate_success(resp)
        assert_subscription_document(data)
        assert "updated_at" not in data, "SubscriptionDocument must not carry updated_at"
        assert "version" not in data, "SubscriptionDocument must not carry version"


class TestOfferingOpenGate:
    def test_offering_not_open_blocks_submit(self, api, investor_headers):
        """PRD §3.3: "The offering must be `OPEN` (`ERR_OFFERING_NOT_OPEN`)";
        a submission against a subscription whose offering has left OPEN is
        rejected.

        Design: Corner/errors/error_offering_not_open_blocks_submit
        """
        syn = make_active_syndication(syndication_name="NoSyn")
        off = make_open_offering(syn["id"], offering_name="No Off")
        inv = make_investor(full_legal_name="No Inv")
        sub = make_draft_subscription(off, inv, 5_000_000, syn["id"])
        # Move the offering out of OPEN before the investor submits.
        validate_success(api.close_offering_to_new(syn["id"], off["id"], SPONSOR))
        resp = api.submit_subscription(syn["id"], off["id"], sub["id"],
                                       make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_OPEN, 409)
