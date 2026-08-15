"""Mailing batches, label generation, postal verification thresholds,
segregation of duties, and batch-level optimistic concurrency."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_mailing_label,
    assert_postal_statement,
    assert_mailing_batch,
    create_publication,
    create_issue,
    create_batch,
    get_mailing_batch,
    generate_labels_with_occ,
    drive_issue_to_at_printer,
    setup_batch_with_labels_generated,
    setup_publication_with_subscriptions,
    drive_batch_to_confirmed,
    drive_issue_to_mailed,
    set_clock,
    PM,
    FM,
    PCO,
)

PM_H = TEST_USERS["production_manager_headers"]
FM_H = TEST_USERS["fulfillment_manager_headers"]
PCO_H = TEST_USERS["postal_compliance_officer_headers"]


class TestMailingLabelImmutability:
    def test_mailing_labels_are_immutable_snapshots(self, api):
        """MailingLabels carry only id and created_at: no updated_at, no
        version.

        PRD §2.5: "Three resources are immutable ledger-style snapshots and carry only `id` and `created_at`: the MailingLabel, the PostalStatement, and the DeferredRevenueEntry. On these three, both `updated_at` and `version` are absent entirely."

        Design: Corner/entities/mailing_label_is_immutable_no_version_field
        """
        ctx = setup_batch_with_labels_generated(num_paid=1)
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        labels = validate_success(
            api.list_mailing_labels(pub_id, issue_id, batch_id, FM_H)
        )
        assert len(labels) == 1, f"one ACTIVE US subscription on a DOMESTIC batch yields one label, got {len(labels)}"
        for label in labels:
            assert_mailing_label(label)


class TestPeriodicalPaidRatioBoundary:
    def test_periodical_verify_at_exactly_5000_bps_passes(self, api):
        """The paid-share floor is inclusive: 2 paid + 2 controlled labels give
        exactly 5000 basis points, which meets "at least fifty percent" and
        verifies successfully.

        PRD §3.4: "For a `PERIODICAL` batch, two thresholds bind: the paid share of its pieces must reach at least fifty percent — 5000 basis points — or verification is rejected with `ERR_PAID_RATIO_BELOW_MINIMUM`, and the issue's advertising share must not exceed seventy-five percent — 7500 basis points — or it is rejected with `ERR_AD_CONTENT_EXCEEDS_LIMIT`."
        PRD §3.4: "A successful verification writes an immutable **PostalStatement** snapshot against the batch (via `batch_id`) whose `form_number` derives from the `postal_class` and takes one of `PS_3541`, `PS_3541_A`, or `PS_3602_R`."

        Design: Difficulty/boundary_precision_check/periodical_paid_ratio_exactly_5000_bps
        """
        ctx = setup_batch_with_labels_generated(
            num_paid=2, num_controlled=2, circulation_model="MIXED",
            postal_class="PERIODICAL", is_controlled_copy_included=True,
        )
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        verified = validate_success(api.verify_postal(pub_id, issue_id, batch_id, PCO_H))
        assert_mailing_batch(verified)
        assert verified["status"] == "POSTAL_VERIFIED"

        statements = validate_success(api.list_postal_statements(pub_id, issue_id, batch_id, PCO_H))
        assert len(statements) == 1
        stmt = statements[0]
        assert_postal_statement(stmt)
        assert stmt["paid_percentage_bps"] == 5000, (
            f"2 paid of 4 pieces truncate to exactly 5000 bps, got {stmt['paid_percentage_bps']}"
        )

    def test_postal_statement_records_piece_counts(self, api):
        """The verification snapshot records the paid and controlled piece
        counts split by each label's is_controlled_copy flag.

        PRD §3.4: "The statement records `paid_piece_count` — the labels whose `is_controlled_copy` is false — and `controlled_piece_count` — those where it is true — and expresses the paid share as `paid_percentage_bps`: the paid piece count multiplied by ten thousand and divided by the total piece count, truncated to a whole number of basis points, and defined as zero when there are no pieces at all."

        Design: Difficulty/boundary_precision_check/periodical_paid_ratio_exactly_5000_bps
        """
        ctx = setup_batch_with_labels_generated(
            num_paid=2, num_controlled=2, circulation_model="MIXED",
            postal_class="PERIODICAL", is_controlled_copy_included=True,
        )
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        validate_success(api.verify_postal(pub_id, issue_id, batch_id, PCO_H))
        statements = validate_success(api.list_postal_statements(pub_id, issue_id, batch_id, PCO_H))
        assert len(statements) == 1
        stmt = statements[0]
        assert stmt["paid_piece_count"] == 2, f"expected 2 paid pieces, got {stmt['paid_piece_count']}"
        assert stmt["controlled_piece_count"] == 2, (
            f"expected 2 controlled pieces, got {stmt['controlled_piece_count']}"
        )
        assert stmt["paid_percentage_bps"] == 5000


class TestPaidPercentageTruncation:
    def test_paid_percentage_truncates_not_rounds(self, api):
        """1 paid of 3 pieces is 3333.33... basis points; the rule truncates
        (floors) to 3333 and never rounds up to 3334.

        PRD §3.4: "The statement records `paid_piece_count` — the labels whose `is_controlled_copy` is false — and `controlled_piece_count` — those where it is true — and expresses the paid share as `paid_percentage_bps`: the paid piece count multiplied by ten thousand and divided by the total piece count, truncated to a whole number of basis points, and defined as zero when there are no pieces at all."
        PRD §2.8: "paid-share figures expressed in basis points truncate (floor) and are never rounded up."

        Design: Corner/calculations/paid_percentage_truncates_not_rounds
        """
        # FIRST_CLASS carries no paid-ratio threshold, so verification succeeds
        # and the truncation is observable on the PostalStatement.
        ctx = setup_batch_with_labels_generated(
            num_paid=1, num_controlled=2, circulation_model="MIXED",
            postal_class="FIRST_CLASS", is_controlled_copy_included=True,
        )
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        validate_success(api.verify_postal(pub_id, issue_id, batch_id, PCO_H))
        statements = validate_success(api.list_postal_statements(pub_id, issue_id, batch_id, PCO_H))
        assert len(statements) == 1
        stmt = statements[0]
        assert stmt["paid_percentage_bps"] == 3333, (
            f"floor(1*10000/3) is 3333, never 3334, got {stmt['paid_percentage_bps']}"
        )


class TestPeriodicalPaidRatioBelowMinimum:
    def test_periodical_verify_below_minimum_paid_ratio_rejected(self, api):
        """1 paid + 3 controlled pieces give 2500 basis points, below the
        5000-bps floor, so postal verification is rejected with
        ERR_PAID_RATIO_BELOW_MINIMUM.

        PRD §3.4: "For a `PERIODICAL` batch, two thresholds bind: the paid share of its pieces must reach at least fifty percent — 5000 basis points — or verification is rejected with `ERR_PAID_RATIO_BELOW_MINIMUM`, and the issue's advertising share must not exceed seventy-five percent — 7500 basis points — or it is rejected with `ERR_AD_CONTENT_EXCEEDS_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_verify_postal
        """
        ctx = setup_batch_with_labels_generated(
            num_paid=1, num_controlled=3, circulation_model="MIXED",
            postal_class="PERIODICAL", is_controlled_copy_included=True,
        )
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        resp = api.verify_postal(pub_id, issue_id, batch_id, PCO_H)
        validate_error(resp, ApiErrorId.ERR_PAID_RATIO_BELOW_MINIMUM, 422)

    def test_failed_verification_leaves_batch_labels_generated(self, api):
        """A rejected verification does not advance the batch: it remains in
        LABELS_GENERATED (only a successful verification moves it to
        POSTAL_VERIFIED).

        PRD §3.4: "Verification moves the batch from `LABELS_GENERATED` to `POSTAL_VERIFIED` and belongs exclusively to the `PostalComplianceOfficer`. For a `PERIODICAL` batch, two thresholds bind: the paid share of its pieces must reach at least fifty percent — 5000 basis points — or verification is rejected with `ERR_PAID_RATIO_BELOW_MINIMUM`, and the issue's advertising share must not exceed seventy-five percent — 7500 basis points — or it is rejected with `ERR_AD_CONTENT_EXCEEDS_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_verify_postal
        """
        ctx = setup_batch_with_labels_generated(
            num_paid=1, num_controlled=3, circulation_model="MIXED",
            postal_class="PERIODICAL", is_controlled_copy_included=True,
        )
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        resp = api.verify_postal(pub_id, issue_id, batch_id, PCO_H)
        validate_error(resp, ApiErrorId.ERR_PAID_RATIO_BELOW_MINIMUM, 422)

        batch = get_mailing_batch(pub_id, issue_id, batch_id)
        assert batch["status"] == "LABELS_GENERATED", (
            f"rejected verification must leave the batch LABELS_GENERATED, got {batch['status']}"
        )


class TestStandardClassNoControlled:
    def test_standard_batch_with_controlled_copies_rejected(self, api):
        """A STANDARD-class batch that declares controlled copies fails
        verification outright.

        PRD §3.4: "For a `STANDARD` batch, controlled copies are forbidden outright: if `is_controlled_copy_included` is true, verification fails with `ERR_STANDARD_NO_CONTROLLED`."

        Design: Corner/validations/standard_postal_class_with_controlled_copy_rejected
        """
        ctx = setup_batch_with_labels_generated(
            num_paid=0, num_controlled=1, circulation_model="MIXED",
            postal_class="STANDARD", is_controlled_copy_included=True,
        )
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        resp = api.verify_postal(pub_id, issue_id, batch_id, PCO_H)
        validate_error(resp, ApiErrorId.ERR_STANDARD_NO_CONTROLLED, 422)


class TestBatchOptimisticConcurrency:
    def test_generate_labels_with_stale_batch_version_rejected(self, api):
        """Label generation is concurrency-guarded: an expected_batch_version
        older than the batch's current version is rejected with
        ERR_STALE_BATCH_VERSION.

        PRD §2.9: "Generating labels for a mailing batch requires `expected_batch_version`, the client's last observed `version` of the MailingBatch. If another operator has modified batch attributes such as its `postal_class` or `entry_point` since the client last read it, the batch's `version` will have advanced and the request is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_batch_version_on_generate_labels
        """
        ctx = setup_publication_with_subscriptions(num_paid=1)
        pub_id, issue_id = ctx["publication"]["id"], ctx["issue"]["id"]
        drive_issue_to_at_printer(pub_id, issue_id)
        batch = create_batch(pub_id, issue_id)
        assert batch["status"] == "DRAFT"

        stale_version = batch["version"] - 1
        resp = api.generate_labels(
            pub_id, issue_id, batch["id"], {"expected_batch_version": stale_version}, FM_H
        )
        validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION, 412)

    def test_second_label_generation_rejected(self, api):
        """Label generation runs only once per batch; a second attempt fails
        with ERR_LABELS_ALREADY_GENERATED. The lifecycle-state check (fourth)
        is evaluated before the expected-version check (fifth), so the state
        error surfaces even though the resubmitted version is also stale.

        PRD §3.4: "It runs only while the issue is `AT_PRINTER` — any other issue state yields `ERR_ISSUE_NOT_AT_PRINTER` — and only once per batch, a second attempt failing with `ERR_LABELS_ALREADY_GENERATED`."
        PRD §2.7: "Fourth, lifecycle-state permissibility — the resource must be in the state the operation starts from (an issue must be `AD_CLOSED` before it can ship to the printer; a subscription must be `ACTIVE` before it can be suspended); violations surface as `ERR_INVALID_STATE` (HTTP 409) unless a more specific state error is defined for the operation. Fifth, on the three concurrency-guarded writes, the expected-version match described in §2.9."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_batch_version_on_generate_labels
        """
        ctx = setup_publication_with_subscriptions(num_paid=1)
        pub_id, issue_id = ctx["publication"]["id"], ctx["issue"]["id"]
        drive_issue_to_at_printer(pub_id, issue_id)
        batch = create_batch(pub_id, issue_id)
        original_version = batch["version"]

        generated = validate_success(
            api.generate_labels(
                pub_id, issue_id, batch["id"],
                {"expected_batch_version": original_version}, FM_H,
            )
        )
        assert generated["status"] == "LABELS_GENERATED"

        resp = api.generate_labels(
            pub_id, issue_id, batch["id"], {"expected_batch_version": original_version}, FM_H
        )
        validate_error(resp, ApiErrorId.ERR_LABELS_ALREADY_GENERATED, 409)


class TestPostalSegregationOfDuties:
    def test_fulfillment_manager_cannot_verify_postal(self, api):
        """The fulfillment operator who built the mailing may not verify its
        compliance: verification belongs exclusively to the
        PostalComplianceOfficer.

        PRD §2.11: "Second, segregation of duties: the operator who builds and tenders a mailing (`FulfillmentManager`) is never the operator who verifies its compliance or confirms its acceptance (`PostalComplianceOfficer`)."
        PRD §2.1: "Section 4 lists, per endpoint, which roles are authorized; an authenticated operator attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/fulfillment_manager_cannot_verify_postal_segregation_of_duties
        """
        ctx = setup_batch_with_labels_generated(num_paid=1)
        pub_id, issue_id, batch_id = (
            ctx["publication"]["id"], ctx["issue"]["id"], ctx["batch"]["id"],
        )
        resp = api.verify_postal(pub_id, issue_id, batch_id, FM_H)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_postal_compliance_officer_cannot_generate_labels(self, api):
        """The inverse segregation holds: the compliance officer may not build
        the mailing by generating its labels — that is FulfillmentManager
        work.

        PRD §2.11: "Second, segregation of duties: the operator who builds and tenders a mailing (`FulfillmentManager`) is never the operator who verifies its compliance or confirms its acceptance (`PostalComplianceOfficer`)."
        PRD §2.1: "Section 4 lists, per endpoint, which roles are authorized; an authenticated operator attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/postal_compliance_officer_cannot_generate_labels
        """
        ctx = setup_publication_with_subscriptions(num_paid=1)
        pub_id, issue_id = ctx["publication"]["id"], ctx["issue"]["id"]
        drive_issue_to_at_printer(pub_id, issue_id)
        batch = create_batch(pub_id, issue_id)

        resp = api.generate_labels(
            pub_id, issue_id, batch["id"], {"expected_batch_version": batch["version"]}, PCO_H
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestMailingRecognitionConsistency:
    def test_mark_mailed_response_reflects_recognition_immediately(self, api):
        """The mark-mailed response itself shows the issue MAILED with
        revenue_recognized_cents already computed — 100 cents for the single
        served 1200-cent, 12-issue PRO_RATA_ISSUE term — with no eventual lag.

        PRD §3.5: "The issue's `revenue_recognized_cents` records the sum of the recognition entries posted against it."
        PRD §3.5: "Under `PRO_RATA_ISSUE`, each issue of the term recognizes the term's `gross_amount_cents` divided by `issues_in_term`, rounded half up to whole cents — except the term's final issue, identified when the count of `RECOGNITION` entries already posted against the term has reached one less than `issues_in_term`, which instead recognizes whatever amount remains so that `recognized_balance_cents` and `deferred_balance_cents` together equal `gross_amount_cents` exactly."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_on_issue_mail_recognition
        """
        ctx = setup_publication_with_subscriptions(num_paid=1, price_paid_cents=1200)
        pub_id, issue_id = ctx["publication"]["id"], ctx["issue"]["id"]
        drive_issue_to_at_printer(pub_id, issue_id)
        batch = create_batch(pub_id, issue_id)
        drive_batch_to_confirmed(pub_id, issue_id, batch["id"])

        mailed = validate_success(api.mark_mailed(pub_id, issue_id, FM_H))
        assert mailed["status"] == "MAILED"
        assert mailed["revenue_recognized_cents"] == 100, (
            f"one served 1200/12 term recognizes 100 cents immediately, got "
            f"{mailed['revenue_recognized_cents']}"
        )
