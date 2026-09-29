"""Serialisers: exactly the field set each entity declares (scaffold 1.1)."""

COMMON = ("id", "created_at", "updated_at", "version")
LEDGER_COMMON = ("id", "created_at")

PUBLISHER = COMMON + (
    "name",
    "publisher_code",
    "country_code",
    "screening_status",
    "predatory_score",
    "doaj_indexed",
    "cope_member",
    "editorial_board_verified",
    "retraction_rate_per_1000",
    "peer_review_days_median",
    "apc_transparency_score",
    "author_guidance",
    "last_screened_at",
    "active_agreement_count",
)

JOURNAL = COMMON + (
    "publisher_id",
    "issn",
    "title",
    "oa_model",
    "list_apc_cents",
    "required_embargo_months",
)

AGREEMENT = COMMON + (
    "publisher_id",
    "agreement_code",
    "effective_from",
    "effective_until",
    "article_quota",
    "articles_used",
    "discount_pct",
    "covered_oa_models",
    "status",
    "activated_at",
)

COVERAGE = LEDGER_COMMON + (
    "agreement_id",
    "journal_id",
    "coverage_type",
    "capped_amount_cents",
    "covered_from",
    "covered_until",
)

AUTHOR = COMMON + (
    "full_name",
    "email",
    "orcid",
    "department_code",
    "affiliation_status",
    "appointment_from",
    "appointment_until",
    "annual_cap_cents",
    "apc_committed_cents",
    "apc_disbursed_cents",
    "linked_output_count",
)

FUNDER = COMMON + (
    "name",
    "funder_code",
    "mandate_type",
    "max_embargo_months",
    "deposit_deadline_days",
    "license_required",
    "apc_allowable",
)

GRANT = COMMON + (
    "funder_id",
    "pi_author_id",
    "grant_number",
    "award_from",
    "award_until",
    "apc_budget_cents",
    "status",
    "output_count",
    "compliant_output_count",
    "mandate_status",
)

ARTICLE = COMMON + (
    "journal_id",
    "corresponding_author_id",
    "grant_id",
    "manuscript_title",
    "accepted_on",
    "publication_date",
    "apc_list_cents",
    "doi",
    "funding_status",
    "compliance_status",
    "eligibility_route",
    "covered_amount_cents",
    "author_share_cents",
    "determination_count",
    "deposit_deadline_on",
    "embargo_until",
    "latest_deposit_ordinal",
)

DETERMINATION = LEDGER_COMMON + (
    "article_id",
    "sequence_no",
    "basis",
    "reference_date",
    "route",
    "agreement_id",
    "coverage_id",
    "list_base_cents",
    "discount_pct_applied",
    "covered_amount_cents",
    "author_share_cents",
    "eligible_request_cents",
    "determination_reason",
    "quota_position",
)

FUND = COMMON + (
    "fund_code",
    "fiscal_year",
    "period_from",
    "period_to",
    "total_budget_cents",
    "committed_cents",
    "spent_cents",
    "available_cents",
    "priority_rank",
    "eligible_affiliation_statuses",
    "per_article_cap_cents",
    "status",
    "freeze_reason",
)

FUND_REQUEST = COMMON + (
    "article_id",
    "requested_cents",
    "justification",
    "status",
    "revision_round",
    "info_needed",
    "response_note",
    "reviewed_by_user_id",
    "decided_by_user_id",
    "decision_reason",
    "approved_cents",
    "author_share_cents",
    "fully_funded",
)

ALLOCATION = COMMON + (
    "fund_request_id",
    "fund_id",
    "amount_cents",
    "sequence_index",
    "status",
    "released_reason",
)

INVOICE = COMMON + (
    "publisher_id",
    "article_id",
    "invoice_number",
    "invoice_amount_cents",
    "currency",
    "claimed_discount_pct",
    "vat_pct",
    "invoice_date",
    "entitled_discount_pct",
    "net_cents",
    "vat_cents",
    "expected_amount_cents",
    "variance_cents",
    "validation_outcome",
    "status",
    "dispute_reason",
    "payment_approved_by_user_id",
    "payment_reference",
)

DEPOSIT = COMMON + (
    "article_id",
    "version_label",
    "version_ordinal",
    "file_checksum",
    "license",
    "status",
    "persistent_identifier",
    "returned_count",
    "curation_note",
    "submitted_at",
    "ingested_at",
    "embargo_until",
)


def serialize(row, fields):
    return dict((key, row.get(key)) for key in fields)


def serialize_many(rows, fields):
    return [serialize(row, fields) for row in rows]
