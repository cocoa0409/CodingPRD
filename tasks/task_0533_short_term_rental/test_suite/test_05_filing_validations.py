"""Tax filing creation and file-time validations.

Covers difficulty queue A instances for the zero-nights boundary and duplicate
period overlap; plus corner queue B instances for file-on-draft-permit and
amend-with-remittance rejections.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_host_headers, TEST_USERS,
    setup_issued_permit, setup_draft_permit, setup_filed_filing,
    create_draft_filing, create_draft_permit,
    create_zone, create_host, create_property,
)

REGISTRAR = TEST_USERS["registrar_headers"]
TAX_OFFICER = TEST_USERS["tax_officer_headers"]


def test_file_zero_nights_rejected(api):
    """PRD §3.8: "It further requires nights_booked to be at least one, since a
    zero-night period has nothing to file; a zero-night filing is rejected with
    ERR_NO_NIGHTS_TO_FILE (HTTP 422)."

    Design: Difficulty/boundary_precision_check/no_nights_zero_count_file_rejected
    """
    _, host, _, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], nights_booked=0, gross_revenue_cents=0)
    validate_error(api.file_tax_filing(draft["id"], TAX_OFFICER), ApiErrorId.ERR_NO_NIGHTS_TO_FILE)


def test_duplicate_filing_period_rejected(api):
    """PRD §3.8: "The triple of permit, year, and month must be unique; a second
    filing for an already-filed period is rejected with ERR_DUPLICATE_FILING_PERIOD
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tax_filing_period_uniqueness_overlap
    """
    _, host, _, permit = setup_issued_permit()
    create_draft_filing(permit["id"], period_year=2026, period_month=3,
                        nights_booked=10, gross_revenue_cents=500000)
    validate_error(
        api.create_tax_filing(
            {"permit_id": permit["id"], "period_year": 2026, "period_month": 3,
             "nights_booked": 5, "gross_revenue_cents": 250000},
            TAX_OFFICER,
        ),
        ApiErrorId.ERR_DUPLICATE_FILING_PERIOD,
    )


def test_file_on_draft_permit_rejected(api):
    """PRD §3.8: "only permits still in DRAFT, REJECTED, or LOTTERY_PENDING cannot
    be filed against, which is rejected with ERR_PERMIT_NOT_FILEABLE (HTTP 422)."

    Design: Corner/validations/file_on_draft_permit_rejected
    """
    zone = create_zone()
    host = create_host()
    prop = create_property(host["id"], zone["id"])
    permit = create_draft_permit(prop["id"], permit_type="WHOLE_HOME")
    draft = create_draft_filing(permit["id"], nights_booked=10, gross_revenue_cents=500000)
    validate_error(api.file_tax_filing(draft["id"], TAX_OFFICER), ApiErrorId.ERR_PERMIT_NOT_FILEABLE)


def test_amend_filing_with_remittance_rejected(api):
    """PRD §3.8: "A tax officer may re-open a FILED filing for correction, but
    only if no money has yet been paid against it - amount_remitted_cents must be
    zero, otherwise the amendment is rejected with ERR_FILING_HAS_REMITTANCES
    (HTTP 422)."

    Design: Corner/validations/amend_filing_with_remittance_rejected
    """
    _, host, _, permit, filed = setup_filed_filing(
        filing_overrides={"nights_booked": 10, "gross_revenue_cents": 500000}
    )
    validate_success(
        api.remit_tax_filing(filed["id"], {"payment_cents": 10000}, make_host_headers(host["id"]))
    )
    validate_error(api.amend_tax_filing(filed["id"], TAX_OFFICER), ApiErrorId.ERR_FILING_HAS_REMITTANCES)
