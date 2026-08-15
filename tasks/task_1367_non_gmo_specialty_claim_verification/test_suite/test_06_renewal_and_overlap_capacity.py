"""Renewal gate tests, affidavit window overlap, and audit capacity."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_brand_rep_headers,
    create_standard, create_brand, create_product, add_ingredient,
    add_accepted_affidavit, create_verified_product,
    open_case, substantiate_case, set_clock,
    create_affidavit_payload, create_facility_audit_payload,
    create_audit_report_payload,
)
from test_helpers import build_user_headers

ADMIN = TEST_USERS["verifier_admin_headers"]


def _auditor_headers(auditor_id):
    return build_user_headers(auditor_id, "Auditor")


# ─── Renewal window and standing gates ───────────────────────────────────────

class TestRenewalGates:
    def test_renew_before_window_returns_window_closed(self, api):
        """PRD section 3.7: "the renewal window currently open — too early or
        at-or-after expiry draws `ERR_RENEWAL_WINDOW_CLOSED`"
        PRD section 3.7: "The renewal window opens `renewal_window_days` before
        the license's `valid_until`"

        Design: Corner/validations/renew_before_window_returns_renewal_window_closed
        """
        ctx = create_verified_product()
        # Window opens 2027-06-02 (valid_until 2027-08-01 minus 60 days); the
        # clock at 2027-01-15 is too early; audit freshness holds to 2027-08-01.
        set_clock("2027-01-15T00:00:00Z")
        res = api.renew_product(
            ctx["product"]["id"], make_brand_rep_headers(ctx["brand"]["id"]))
        validate_error(res, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value)

    def test_renew_with_probation_brand_returns_brand_on_probation(self, api):
        """PRD section 3.7: "the brand's `standing_status` must be
        `GOOD_STANDING` — probation blocks renewal with `ERR_BRAND_ON_PROBATION`"
        PRD section 3.8: "and `standing_status` flips to `PROBATION` exactly when
        the lifetime total reaches 20 or more, otherwise `GOOD_STANDING`."

        Design: Corner/validations/renew_with_probation_brand_returns_brand_on_probation
        """
        ctx = create_verified_product()
        brand, std = ctx["brand"], ctx["standard"]
        p2 = create_product(brand, std, name="P2", gtin="G-P2")
        p3 = create_product(brand, std, name="P3", gtin="G-P3")
        c1 = open_case(p2["id"], source="RETEST_FAILURE", description="d")
        substantiate_case(c1["id"], sanction="LICENSE_SUSPENSION")
        c2 = open_case(p3["id"], source="RETEST_FAILURE", description="d")
        substantiate_case(c2["id"], sanction="LICENSE_SUSPENSION")

        set_clock("2027-06-15T00:00:00Z")
        res = api.renew_product(
            ctx["product"]["id"], make_brand_rep_headers(brand["id"]))
        validate_error(res, ApiErrorId.ERR_BRAND_ON_PROBATION.value)

    def test_renew_with_recent_penalties_returns_recent_penalties(self, api):
        """PRD section 3.7: "`rolling_penalty_points` below 10"
        PRD section 3.8: "These counters gate the program: probation blocks new
        enrollment and renewal, and a rolling total of 10 or more blocks
        verification decisions and renewal."

        Design: Corner/validations/renew_with_recent_penalties_returns_recent_penalties
        """
        ctx = create_verified_product()
        brand, std = ctx["brand"], ctx["standard"]
        p2 = create_product(brand, std, name="P2", gtin="G-P2")
        c1 = open_case(p2["id"], source="CONSUMER_COMPLAINT", description="d")
        substantiate_case(c1["id"], sanction="WARNING")
        c2 = open_case(p2["id"], source="MARKETPLACE_MONITOR", description="d2")
        substantiate_case(c2["id"], sanction="WARNING")

        set_clock("2027-06-15T00:00:00Z")
        brand_after = validate_success(api.get_brand(brand["id"], ADMIN), 200)
        assert brand_after["standing_status"] == "GOOD_STANDING"
        assert brand_after["rolling_penalty_points"] == 10

        res = api.renew_product(
            ctx["product"]["id"], make_brand_rep_headers(brand["id"]))
        validate_error(res, ApiErrorId.ERR_BRAND_RECENT_PENALTIES.value)

    def test_renew_success_extends_license_from_old_expiry(self, api):
        """PRD section 3.7: "A successful renewal extends `valid_until` by
        `license_term_days` days counted from the current `valid_until`, not from
        the renewal date, and returns a `RENEWAL_DUE` product to `VERIFIED`."

        Design: Corner/validations/renew_success_extends_license
        """
        ctx = create_verified_product()
        set_clock("2027-06-15T00:00:00Z")
        product = get_product_status(api, ctx["product"]["id"])
        assert product["enrollment_status"] == "RENEWAL_DUE"

        res = api.renew_product(
            ctx["product"]["id"], make_brand_rep_headers(ctx["brand"]["id"]))
        renewed = validate_success(res, 200)
        assert renewed["enrollment_status"] == "VERIFIED"

        licenses = validate_success(
            api.list_licenses(ADMIN, params={"product_id": ctx["product"]["id"]}), 200)
        assert licenses[0]["status"] == "ACTIVE"
        # 2027-08-01 + 365 days; leap-2028 makes 2028-08-01 the 366th day.
        assert str(licenses[0]["valid_until"]).startswith("2028-07-31T00:00:00")


def get_product_status(api, product_id):
    return validate_success(api.get_product(product_id, ADMIN), 200)


# ─── Affidavit window half-open overlap ──────────────────────────────────────

def _setup_accepted_acme_affidavit(api):
    """DRAFT product with HIGH_RISK ingredient; ACCEPTED affidavit for supplier
    Acme covering [2026-01-01, 2026-07-01)."""
    std = create_standard()
    brand = create_brand(name="B1", contact_email="b1@x.com")
    product = create_product(brand, std, name="P1", gtin="G-P1")
    ing = add_ingredient(product["id"], brand["id"])
    add_accepted_affidavit(ing["id"], brand["id"], supplier_name="Acme",
                           valid_from="2026-01-01T00:00:00Z",
                           valid_until="2026-07-01T00:00:00Z")
    return brand, ing


class TestAffidavitWindowOverlap:
    def test_overlapping_window_rejected(self, api):
        """PRD section 3.4: "For a given ingredient and supplier pair, the new
        window must not overlap any sibling affidavit that is still `SUBMITTED` or
        `ACCEPTED`; overlap is rejected with `ERR_AFFIDAVIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/affidavit_window_half_open_adjacency
        """
        brand, ing = _setup_accepted_acme_affidavit(api)
        res = api.create_affidavit(
            create_affidavit_payload(ing["id"], supplier_name="Acme",
                                     valid_from="2026-06-01T00:00:00Z",
                                     valid_until="2027-01-01T00:00:00Z"),
            make_brand_rep_headers(brand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_AFFIDAVIT_WINDOW_OVERLAP.value)

    def test_adjacent_window_accepted(self, api):
        """PRD section 3.4: "Windows are half-open: coverage includes the
        `valid_from` instant and runs up to but excludes `valid_until`, and
        `valid_until` must be strictly later than `valid_from`."
        PRD section 3.4: "Because the windows are half-open, strict adjacency is
        allowed — a new affidavit whose `valid_from` equals the sibling's
        `valid_until` tiles cleanly."

        Design: Difficulty/resource_temporal_overlap/affidavit_window_half_open_adjacency
        """
        brand, ing = _setup_accepted_acme_affidavit(api)
        res = api.create_affidavit(
            create_affidavit_payload(ing["id"], supplier_name="Acme",
                                     valid_from="2026-07-01T00:00:00Z",
                                     valid_until="2027-01-01T00:00:00Z"),
            make_brand_rep_headers(brand["id"]),
        )
        aff = validate_success(res, 201)
        assert aff["id"]


# ─── Facility audit capacity cardinality ─────────────────────────────────────

class TestAuditCapacity:
    def test_second_open_audit_same_facility_rejected(self, api):
        """PRD section 3.6: "Capacity is gated per facility: at most one audit may
        sit in `SCHEDULED` or `REPORT_SUBMITTED` status for a given `brand_id` and
        `facility_name` pair, and a second scheduling attempt is rejected with
        `ERR_AUDIT_CAPACITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/facility_audit_capacity_cardinality
        """
        brand = create_brand(name="B1", contact_email="b1@x.com")
        validate_success(
            api.create_facility_audit(
                create_facility_audit_payload(brand["id"], facility_name="F1",
                                              auditor_id="aud-1"), ADMIN), 201)
        res = api.create_facility_audit(
            create_facility_audit_payload(
                brand["id"], facility_name="F1", auditor_id="aud-1",
                scheduled_date="2026-12-01T00:00:00Z"),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_AUDIT_CAPACITY_CONFLICT.value)

    def test_capacity_frees_after_terminal_decision(self, api):
        """PRD section 3.6: "Capacity is gated per facility: at most one audit may
        sit in `SCHEDULED` or `REPORT_SUBMITTED` status for a given `brand_id` and
        `facility_name` pair"
        PRD section 3.6: "Either decision stamps `decided_at` with the current
        logical time and is terminal."

        Design: Difficulty/resource_temporal_overlap/facility_audit_capacity_cardinality
        """
        brand = create_brand(name="B1", contact_email="b1@x.com")
        a1 = validate_success(
            api.create_facility_audit(
                create_facility_audit_payload(brand["id"], facility_name="F1",
                                              auditor_id="aud-1"), ADMIN), 201)
        validate_success(
            api.submit_audit_report(a1["id"], create_audit_report_payload(),
                                    _auditor_headers("aud-1")), 200)
        validate_success(api.decide_audit(a1["id"], {"decision": "PASSED"}, ADMIN), 200)
        res = api.create_facility_audit(
            create_facility_audit_payload(
                brand["id"], facility_name="F1", auditor_id="aud-1",
                scheduled_date="2026-12-01T00:00:00Z"),
            ADMIN,
        )
        validate_success(res, 201)
