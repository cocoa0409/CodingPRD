# Vendor Tax Reporting 1099 API — Product Requirements Document

## 1. Introduction

Every year, accounts payable organizations must answer a deceptively simple question for each vendor they paid: does this vendor require an information return, for how much, in which boxes, and was any of it subject to backup withholding? Getting the answer wrong invites IRS penalties, CP2100 B-notices, and laborious correction cycles. The work spans the entire reporting season — collecting W-9 forms and matching taxpayer identification numbers at onboarding, classifying each payment into the correct 1099 box as it is posted, withholding and remitting federal tax when a vendor's TIN cannot be verified, aggregating a full year of payments across multiple source systems, producing 1099-NEC and 1099-MISC returns, delivering recipient copies, transmitting to the IRS, honoring state direct-reporting obligations, and cleaning up the duplicate vendor records that quietly corrupt all of the above.

This document specifies the API for that domain: a 1099 vendor reporting and W-9 collection service mounted under `/tax1099`. The service is operated by accounts payable clerks, tax specialists, an authorized transmitter, tax administrators, inbound IRS system feeds, and a vendor self-service portal. It maintains a signed withholding ledger whose quarterly remittances are segregated between preparer and submitter, distinguishes provisional return snapshots from final re-aggregations, models the IRS e-filing threshold that forces electronic transmission once a payer's return count crosses a configured line, and runs the B-notice escalation process that can lock a vendor into backup withholding until an administrator overrides it. All temporal rules — recipient copy deadlines, the trailing three-year mismatch window, and state-rule effectiveness — are evaluated against a controllable logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles: `APClerk`, `TaxSpecialist`, `TaxTransmitter`, `TaxAdmin`, `IRSSystem`, and `VendorPortal`. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to every endpoint is restricted by role, and an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

For five of the six roles — `APClerk`, `TaxSpecialist`, `TaxTransmitter`, `TaxAdmin`, and `IRSSystem` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a remittance draft, `sealed_by_user_id` on a transmittal, `requested_by_user_id` on a merge request, or `resolved_by_user_id` on a B-notice) but does not compare it to any entity's `id`. When `X-User-Role` is `VendorPortal`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare the resource's foreign-key field to `X-User-ID`, so a portal caller may submit a W-9 only for its own vendor record and may read only its own vendor record — any other vendor id in the path yields `ERR_FORBIDDEN_FOR_ROLE`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The service evaluates every temporal rule against a logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any administrative call it continues to read that default. A `TaxAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Three families of rules consume the logical clock: recipient copy delivery is accepted only when the clock reads at or before the covering tax year's `recipient_copy_deadline`; a vendor's `mismatch_count_3yr` counts mismatch events within the trailing three-year window ending at the clock; and a state reporting rule is effective only when the clock falls inside its closed effective interval. Because the clock is deterministic, two evaluations performed at the same logical instant always agree.

### 2.5. Common Resource Properties

All primary resources — TaxYear, Vendor, W9Submission, Payment, Remittance, TaxReturn, Transmittal, StateRule, StateObligation, BNotice, and VendorMergeRequest — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every mutation of the resource; it anchors optimistic concurrency control where that mechanism applies.

Withholding ledger entries are the deliberate exception: a `WithholdingEntry` is an immutable ledger row that carries only `id` and `created_at`. Both `updated_at` and `version` are absent from withholding entries.

### 2.6. Money, Basis Points, and Rounding

All monetary amounts in the system are integer cents — `amount_cents`, `withheld_cents`, `statutory_expected_cents`, `reportable_amount_cents`, and the box-amount fields are whole-cent integers, never floats. Wherever a multiplication produces a fractional cent, the result is rounded half-up to whole cents. Rates are expressed in basis points: the backup withholding rate lives on the tax year as `backup_withholding_rate_bps`, defaults to 2400 (that is, 24 percent), and converts to a multiplier by dividing by ten thousand.

One rounding order is pinned and non-negotiable: backup withholding is rounded per payment first, and ledger balances and remittance totals are sums of those per-payment rounded values. The alternative order — summing gross payments, multiplying, and rounding once — is forbidden for the ledger because it diverges from per-payment rounding by up to one cent per payment. (The statutory comparison figure described in §3.5 is the one place a single aggregate rounding is performed, and it is exposed alongside the ledger total precisely so the two bases can be reconciled.)

### 2.7. Validation Precedence

Every request walks an ordered ladder of checks, and a failure at any rung short-circuits the ladder — the caller always receives the earliest applicable rejection, never a later one that an earlier failure would have masked. The rungs, in evaluation order, are:

1. **Authentication context.** `X-User-ID` and `X-User-Role` must be present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization.** The caller's role must be listed for the endpoint, and a `VendorPortal` caller's `X-User-ID` must equal the path vendor's id (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Existence.** Every identifier in the path must resolve to an existing resource, validated left to right (`ERR_NOT_FOUND`).
4. **State legality.** The target resource must be in a from-state of the requested transition (`ERR_INVALID_STATE_TRANSITION`).
5. **Optimistic concurrency.** Where an endpoint is OCC-guarded, the request's expected-version field must equal the parent entity's current `version` (`ERR_STALE_VERSION`).
6. **W-9 and TIN compliance.** Operations that require a resolved W-9 or a clean second-B-notice posture (`ERR_W9_NOT_ON_FILE`, `ERR_UNRESOLVED_SECOND_B_NOTICE`).
7. **Segregation of duties.** The same user id may not appear on both sides of a segregated step (`ERR_SEGREGATION_OF_DUTIES`).
8. **Temporal rules.** Payment dates must fall inside an existing, open tax-year period, and copy delivery must precede the year's copy deadline (`ERR_NO_TAX_YEAR`, `ERR_TAX_YEAR_CLOSED`, `ERR_COPY_DEADLINE_PASSED`).
9. **Referential usability.** Referenced vendors must be usable for the operation — active, distinct on a merge, TIN-equal on a merge, and free of blocking obligations (`ERR_VENDOR_NOT_ACTIVE`, `ERR_SELF_MERGE`, `ERR_TIN_MISMATCH_ON_MERGE`, `ERR_VENDOR_HAS_OPEN_OBLIGATIONS`).
10. **Structural rules.** TIN shape, period and rule-interval overlap, transmittal non-emptiness, channel and consent constraints, the single-active-correction rule, and payment voidability (`ERR_INVALID_TIN_FORMAT`, `ERR_TAX_YEAR_OVERLAP`, `ERR_STATE_RULE_OVERLAP`, `ERR_TRANSMITTAL_EMPTY`, `ERR_EFILE_REQUIRED`, `ERR_ELECTRONIC_CONSENT_REQUIRED`, `ERR_RETURN_NOT_CORRECTABLE`, `ERR_PAYMENT_NOT_VOIDABLE`).
11. **Fiscal rules.** Payment amounts must be positive, and a remittance must cover a non-empty, positive-sum entry set (`ERR_INVALID_AMOUNT`, `ERR_NOTHING_TO_REMIT`).

Malformed bodies, unknown fields, invalid enum members, missing required fields, and bad date ranges are rejected with `ERR_INVALID_REQUEST` wherever they arise in the ladder.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint takes a version field. Updating a vendor master record requires the request to carry `expected_vendor_version`, the client-side copy of the vendor's `version` from its last read; if the vendor's current `version` has advanced past the supplied value, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read before retrying. Creating a correction against an accepted return likewise requires `expected_return_version`, the client-side copy of the original return's `version`; if another writer has advanced that version since the client last read it, the correction is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client may be acting on a view that predates a competing correction draft. A successful OCC-guarded write increments the guarded entity's `version` by one.

### 2.9. Nested Path Resolution

When an endpoint path contains multiple resource identifiers, the system validates each identifier's existence in strict left-to-right order and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve, before any later identifier or any business rule is examined. A W-9 submission addressed to a nonexistent vendor therefore fails on the vendor id before the submission payload is ever considered, and an action on a nonexistent remittance, return, transmittal, obligation, notice, entry, or merge request fails the same way.

### 2.10. The Withholding Ledger and the Unremitted Pool

Backup withholding is tracked as a ledger of signed entries rather than as a mutable balance. Every ledger row has an `entry_type` — `DEBIT_WITHHELD` rows carry a positive `amount_cents`, `REVERSAL` rows carry a negative `amount_cents` — and a `status` of `UNREMITTED`, `REMITTED`, or `REVERSED`. A vendor's `withholding_balance_cents` is always the signed sum of that vendor's entries whose status is `UNREMITTED`; nothing else contributes. Reversal is modeled as a compensating pair: the original debit moves to `REVERSED`, a new `REVERSAL` entry naming it via `reverses_entry_id` is created already in `REVERSED` status, and the pair nets to zero so it leaves the `UNREMITTED` pool atomically — the balance and any draft remittance totals move in the same step. When a remittance is submitted, the entries it sweeps are stamped with its id in `remittance_id` and move to `REMITTED`, permanently exiting the pool. Because entries are immutable ledger rows, their only lifecycle is this status movement; every balance the API exposes is derived from the rows, never stored independently of them.

### 2.11. Segregation of Duties

Preparation and submission are deliberately split across hands. The `TaxTransmitter` who submits a remittance must not be the `TaxSpecialist` whose id was recorded as `created_by_user_id` when the draft was created; the `TaxTransmitter` who submits a transmittal must not be the `TaxSpecialist` recorded as `sealed_by_user_id`; and the `TaxAdmin` who approves a vendor merge, recorded as `reviewed_by_user_id`, must not be the `APClerk` recorded as `requested_by_user_id`. Any of these collisions is rejected with `ERR_SEGREGATION_OF_DUTIES`.

## 3. Business Logic & Workflows

### 3.1. Configuring the Reporting Year: Tax Years and State Rules

Before anything can be reported, a `TaxAdmin` configures the calendar. A tax year is created with its `tax_year` integer (unique across all tax-year rows), an inclusive `period_start`, an exclusive `period_end_exclusive` — together forming a half-open interval that covers the period — and a `recipient_copy_deadline`, the latest logical-clock instant at which recipient copy delivery is accepted, inclusive of that instant. Three threshold knobs are optional at creation: `efiling_threshold_count` defaults to 10, `nec_reportable_threshold_cents` defaults to 60000 (six hundred dollars), and `misc_reportable_threshold_cents` defaults to 60000. The year's `backup_withholding_rate_bps` is system-set to 2400. Creation is rejected with `ERR_INVALID_REQUEST` when the exclusive end does not fall after the start or when `tax_year` duplicates an existing row, and with `ERR_TAX_YEAR_OVERLAP` when the new half-open period intersects any existing tax year's period — under half-open semantics a period that merely touches a neighbor's endpoint does not overlap it. A new tax year begins `OPEN`.

Closing the year, a `TaxAdmin` action valid only while the year is `OPEN` (any other state draws `ERR_INVALID_STATE_TRANSITION`), moves it to the terminal `CLOSED` state. Once closed, payments whose `payment_date` falls inside the year's half-open period can no longer be created (`ERR_TAX_YEAR_CLOSED`) or voided (`ERR_PAYMENT_NOT_VOIDABLE`).

Alongside the calendar, a `TaxAdmin` registers state reporting rules. Each rule carries a two-letter `state_code`, a `participates_in_cfsf` flag marking whether the state receives federal data through the Combined Federal/State Filing program, a `direct_reporting_threshold_cents` amount, and a closed effective interval from `effective_from` through `effective_to`, both endpoints inclusive. A rule whose `effective_to` precedes its `effective_from` is rejected with `ERR_INVALID_REQUEST`. Two rules for the same `state_code` may not overlap: creation is rejected with `ERR_STATE_RULE_OVERLAP` whenever an existing rule for that state has its `effective_from` at or before the new rule's `effective_to` and the new rule's `effective_from` is at or before the existing rule's `effective_to` — because the intervals are closed, rules whose endpoints merely touch do overlap and are rejected.

### 3.2. Vendor Onboarding and Master Data Maintenance

An `APClerk` (or a `TaxAdmin`) onboards a vendor by supplying its `legal_name` exactly as it should appear on filings, its `entity_classification`, and its mailing address as `address_line1`, `address_city`, `address_state` (a two-letter code that later drives state direct-reporting obligations), and `address_postal`. The classification is one of `INDIVIDUAL_SOLE_PROP`, `C_CORP`, `S_CORP`, `PARTNERSHIP`, `LLC_C`, `LLC_S`, `LLC_P`, `TRUST_ESTATE`, or `TAX_EXEMPT`. The `tin` and `tin_type` (`SSN` or `EIN`) are optional at onboarding — the TIN is normally populated later from a matched W-9 — but a `tin` supplied up front must be exactly nine ASCII digits or the request fails with `ERR_INVALID_TIN_FORMAT`. The `e_delivery_consent` flag, defaulting to false, records the vendor's consent to electronic Copy B delivery. A fresh vendor starts `ACTIVE`, with `tin_match_status` at `NOT_SUBMITTED`, `b_notice_stage` at `NONE`, `mismatch_count_3yr` at zero, and `withholding_balance_cents` at zero. The vendor list can be narrowed with the `status`, `tin_match_status`, `b_notice_stage`, and `merged_into_vendor_id` filters; a `VendorPortal` caller reads only its own record, while `APClerk`, `TaxAdmin`, and `TaxSpecialist` roles read any.

Two system-maintained vendor fields govern withholding posture. The `backup_withholding_flag` is computed, never set directly: it is true exactly when the vendor's `tin_match_status` is `MISMATCHED` or its `b_notice_stage` is `SECOND`, and it gates per-payment withholding at posting time. The `mismatch_count_3yr` counts this vendor's `MISMATCHED` W-9 submissions whose creation timestamps fall within the trailing three-year window ending at the logical clock.

Master data changes — `legal_name`, the four address fields, `e_delivery_consent`, and `entity_classification` — are applied by an `APClerk` or `TaxAdmin` through the OCC-guarded update described in §2.8, which requires `expected_vendor_version` and answers `ERR_STALE_VERSION` on a version mismatch. A successful update increments the vendor's `version` by one. Updating a vendor that has been `MERGED` or `DEACTIVATED` is rejected with `ERR_VENDOR_NOT_ACTIVE`. Changing `entity_classification` has a one-directional consequence: every `DRAFT` or `VALIDATED` return for the vendor's open years is invalidated — `VALIDATED` returns revert to `DRAFT` — with box amounts recomputed on the final basis, while posted payments are never reclassified, because their box classification was fixed at posting time.

When a vendor's affairs are fully settled, a `TaxAdmin` may deactivate it. Deactivation requires the vendor's `withholding_balance_cents` to be exactly zero and no `DRAFT` or `VALIDATED` return to exist for the vendor; either condition blocks the action with `ERR_VENDOR_HAS_OPEN_OBLIGATIONS`. A successful deactivation moves the vendor to the terminal `DEACTIVATED` state.

### 3.3. W-9 Collection and TIN Matching

W-9 intake is shared between the back office and the vendor itself: an `APClerk` may submit on any active vendor's behalf, while a `VendorPortal` caller may submit only against its own vendor id. The submission captures `submitted_legal_name` (the name exactly as written on the form), `submitted_tin` (exactly nine ASCII digits, enforced as `ERR_INVALID_TIN_FORMAT`), `submitted_tin_type` (`SSN` or `EIN`), and `signature_name` as the signer's attestation. The vendor must be `ACTIVE`; submissions against a merged or deactivated vendor are rejected with `ERR_VENDOR_NOT_ACTIVE`. A new submission starts with `match_result` at `PENDING`, and its creation moves the vendor's `tin_match_status` into `PENDING_MATCH` — whether the vendor was previously `NOT_SUBMITTED`, `MATCHED`, or `MISMATCHED`. Re-submission from `MISMATCHED` recomputes the `backup_withholding_flag`: it remains true only while the vendor's `b_notice_stage` is `SECOND`.

The IRS TIN-matching feed, acting as `IRSSystem`, records the outcome for a pending submission by supplying `match_result` as `MATCHED` or `MISMATCHED` plus an optional `mismatch_reason_code`. The submission must still be `PENDING` (otherwise `ERR_INVALID_STATE_TRANSITION`), the vendor must be `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`), and a `MISMATCHED` result delivered without `mismatch_reason_code` is rejected with `ERR_INVALID_REQUEST`.

A `MATCHED` result completes the vendor's identity record: the vendor's `tin`, `tin_type`, and `legal_name` are overwritten with `submitted_tin`, `submitted_tin_type`, and `submitted_legal_name`, the vendor's `tin_match_status` becomes `MATCHED`, and the `backup_withholding_flag` is recomputed — true only if the vendor's `b_notice_stage` is `SECOND`. A `MISMATCHED` result moves the vendor to `MISMATCHED`, increments `mismatch_count_3yr` by one, sets the `backup_withholding_flag` to true, and copies the supplied `mismatch_reason_code` onto the submission. While a vendor sits in `PENDING_MATCH`, return validation is blocked with `ERR_W9_NOT_ON_FILE`; returns already `VALIDATED` when a re-submission lands are unaffected and simply wait for the new result. Submissions can be listed with the `vendor_id` and `match_result` filters.

### 3.4. Payment Recording, Box Classification, and Withholding at Posting

An `APClerk` records each payment with its `vendor_id`, the `source_system` it arrived through, the `payment_type`, a positive gross `amount_cents`, and the `payment_date`. Four source systems — `AP_ERP`, `CORP_CARD`, `MANUAL`, and `FIELD_OFFICE` — feed the same ledger, and payments from all four aggregate onto a single vendor-year return. The payment type is one of `SERVICE`, `RENT`, `ROYALTY`, `ATTORNEY_FEE`, `MEDICAL_HEALTH`, `PRIZE_AWARD`, `GOODS`, or `REIMBURSEMENT`. A missing or non-positive `amount_cents` draws `ERR_INVALID_AMOUNT`. Posting is guarded by the vendor's compliance posture: the vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), its `tin_match_status` must be `MATCHED` or `MISMATCHED` (`ERR_W9_NOT_ON_FILE`), the `payment_date` must fall inside an existing tax year's half-open period (`ERR_NO_TAX_YEAR`), and that year must still be `OPEN` (`ERR_TAX_YEAR_CLOSED`). The payment's `tax_year` is computed as the calendar year of `payment_date`, and its withholding quarter is the payment month divided by three and rounded up to a whole number, yielding one through four. Payments may be listed with the `vendor_id`, `tax_year`, `payment_type`, `source_system`, and `status` filters.

Box classification runs once, at posting, against the vendor's then-current `entity_classification`, and the result is frozen onto the payment as `is_reportable` and `reportable_box`. The corporate-exempt classifications are `C_CORP`, `S_CORP`, `LLC_C`, and `LLC_S`. Payments of type `GOODS` or `REIMBURSEMENT` are never reportable and map to `NONE`. `ATTORNEY_FEE` payments are always reportable to `NEC_1` — the corporate exemption does not apply — and `MEDICAL_HEALTH` payments are always reportable to `MISC_6`, likewise exempt from the corporate exemption. For the remaining types the corporate exemption applies: a `SERVICE` payment maps to `NEC_1` unless the vendor is corporate-exempt (then `NONE`); `RENT` maps to `MISC_1`, `ROYALTY` to `MISC_2`, and `PRIZE_AWARD` to `MISC_3`, each unless the vendor is corporate-exempt. Because classification is frozen at posting, a later change to the vendor's `entity_classification` invalidates open returns but never rewrites posted payments.

Backup withholding is decided at the same instant. When the vendor's `backup_withholding_flag` is true at posting, the payment's `withheld_cents` is the gross `amount_cents` multiplied by the covering tax year's `backup_withholding_rate_bps`, divided by ten thousand, and rounded half-up to whole cents — per the pinned per-payment rounding order of §2.6; when the flag is false, `withheld_cents` is zero. Whenever `withheld_cents` is greater than zero, posting also creates a `DEBIT_WITHHELD` ledger entry in `UNREMITTED` status carrying the payment's `vendor_id`, `payment_id`, `tax_year`, and `quarter`; the vendor's `withholding_balance_cents` is recomputed, and every `DRAFT` remittance covering that year-quarter recomputes its total.

A posted payment can be voided by an `APClerk` or `TaxAdmin` only while it is `POSTED` (otherwise `ERR_INVALID_STATE_TRANSITION`). Voiding is blocked with `ERR_PAYMENT_NOT_VOIDABLE` when the covering tax year is `CLOSED`, when the payment is included in any `ACCEPTED` return, or when the payment's withholding entry has already been `REMITTED`. A successful void moves the payment to `VOIDED` and cascades: if its `withheld_cents` was greater than zero, the original `DEBIT_WITHHELD` entry becomes `REVERSED` and a compensating `REVERSAL` entry of negative `withheld_cents` is created already `REVERSED`, the pair netting to zero and leaving the unremitted pool atomically; the vendor's `withholding_balance_cents` is recomputed; every `DRAFT` remittance for the payment's year-quarter recomputes; and the vendor's `DRAFT` and `VALIDATED` returns for the payment's tax year recompute their box amounts on the final basis, with `VALIDATED` returns reverting to `DRAFT`.

### 3.5. The Withholding Ledger and Quarterly Remittance

Ledger entries can be inspected individually or listed with the `vendor_id`, `payment_id`, `remittance_id`, `reverses_entry_id`, `entry_type`, `status`, and `tax_year` filters. Occasionally a debit was withheld in error and must be unwound before remittance: a `TaxAdmin` may reverse an entry manually, but only a `DEBIT_WITHHELD` entry may be reversed — reversing a `REVERSAL` entry is rejected with `ERR_INVALID_STATE_TRANSITION` — and only while it is `UNREMITTED` (a `REMITTED` entry draws `ERR_ENTRY_ALREADY_REMITTED`; an already-`REVERSED` entry draws `ERR_INVALID_STATE_TRANSITION`). The reversal creates a compensating `REVERSAL` entry of negative `amount_cents` whose `reverses_entry_id` names the original, both rows resting in `REVERSED`; the vendor's `withholding_balance_cents` is recomputed, draft remittances recompute, and the vendor's `DRAFT` and `VALIDATED` returns recompute their `box_4_cents` — the federal-tax-withheld box — with `VALIDATED` returns reverting to `DRAFT`.

Quarterly, a `TaxSpecialist` drafts a remittance by naming its `tax_year` and `quarter`; the draft records the caller as `created_by_user_id`. The draft's `amount_cents` is computed on the accrual basis — the signed sum of all `UNREMITTED` entries matching that year-quarter — and is recomputed on every entry mutation while the remittance remains `DRAFT`. Drafting is rejected with `ERR_NOTHING_TO_REMIT` when the matching entry set is empty or sums to zero or less.

Submission belongs to a `TaxTransmitter`, and it is a hard gate. The remittance must be `DRAFT`; the submitter must differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); and the recomputed `amount_cents` must be greater than zero at submit time (`ERR_NOTHING_TO_REMIT` covers a draft whose entries have drained away). A successful submit sweeps every `UNREMITTED` entry for the year-quarter into `REMITTED`, stamps each with the remittance's id in `remittance_id`, recomputes each affected vendor's balance, locks `amount_cents`, and computes and freezes `statutory_expected_cents` — the statutory comparison figure, which multiplies the sum of gross `amount_cents` over the year-quarter's `POSTED` payments whose `withheld_cents` is greater than zero by the year's rate in basis points divided by ten thousand, rounding half-up once over the aggregate. The two bases legitimately diverge: the accrual figure sums per-payment rounded values while the statutory figure rounds once, so the API exposes both and never rejects on their difference.

The IRS feed then records the remittance's `outcome`. An `ACKNOWLEDGED` outcome moves the remittance to its terminal `ACKNOWLEDGED` state. A `REJECTED` outcome un-sweeps the entries: they return to `UNREMITTED`, their `remittance_id` is cleared, and each vendor's balance is recomputed. Any other `outcome` value is rejected with `ERR_INVALID_REQUEST`, and the feed is honored only while the remittance is `SUBMITTED` (`ERR_INVALID_STATE_TRANSITION`). A `TaxSpecialist` may reopen a `REJECTED` remittance, returning it to `DRAFT` and recomputing `amount_cents` from the current `UNREMITTED` entries.

### 3.6. Return Generation, Validation, and Correction

Return generation is a bulk, threshold-gated operation driven by a `TaxSpecialist` supplying a `tax_year`. When no tax-year row exists for that year the call fails with `ERR_NO_TAX_YEAR`. Otherwise the scan considers every vendor regardless of lifecycle state — `ACTIVE`, `MERGED`, and `DEACTIVATED` vendors alike are scanned, because a merged-away duplicate's payments ride on the surviving vendor via re-parented `vendor_id` — which effectively means every vendor holding `POSTED` reportable payments for the year. For each such vendor the system aggregates box sums over the vendor's `POSTED`, reportable payments for the year, grouped by `reportable_box`, and computes `box_4_cents` as the sum of `withheld_cents` over the same `POSTED` in-year payment set, regardless of reportability. An NEC return exists for the vendor-year exactly when the `NEC_1` total is at least the year's `nec_reportable_threshold_cents`; a MISC return exists exactly when the sum of the `MISC_1`, `MISC_2`, `MISC_3`, and `MISC_6` totals is at least the year's `misc_reportable_threshold_cents`. A return's `box_amounts` map carries `box_1_cents`, `box_2_cents`, `box_3_cents`, `box_4_cents`, and `box_6_cents`, with unused boxes at zero; the `NEC_1` total populates `box_1_cents` of an NEC form, while the `MISC_1`, `MISC_2`, `MISC_3`, and `MISC_6` totals populate `box_1_cents`, `box_2_cents`, `box_3_cents`, and `box_6_cents` of a MISC form respectively.

Generation captures a provisional snapshot: the aggregation runs over the payments that exist at the moment of the call, and the result is frozen into both `provisional_box_amounts` and `box_amounts` with `amount_basis` set to `PROVISIONAL`. The provisional snapshot is never overwritten afterward. A final-basis aggregation — over all of the vendor's `POSTED` in-year payments, including payments recorded after generation but dated in-year — overwrites `box_amounts` and sets `amount_basis` to `FINAL`; this happens at transmittal seal and on every invalidation event (payment void or withholding reversal on the same vendor-year, a merge re-parent, or an `entity_classification` change). Generation is idempotent per key: when a vendor-year-form combination already has a non-terminal return (`DRAFT`, `VALIDATED`, `TRANSMITTED`, or `ACCEPTED`), that combination is skipped and counted. The response reports `generated_count`, the `generated_return_ids` array, and `skipped_count`. Returns can be listed with the `vendor_id`, `tax_year`, `form_type`, `federal_status`, `transmittal_id`, and `corrects_return_id` filters.

A `TaxSpecialist` validates a draft return to certify it for transmission. Validation requires the return to be `DRAFT` (otherwise `ERR_INVALID_STATE_TRANSITION`), the vendor's `tin_match_status` to be `MATCHED` or `MISMATCHED` with a non-null `tin` (otherwise `ERR_W9_NOT_ON_FILE` — so a vendor sitting in `PENDING_MATCH` cannot be validated), and the vendor to be `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`). A validated return can still be pulled back: the invalidation events above revert it to `DRAFT` with recomputed final-basis box amounts. An erroneous draft can also be voided outright by a `TaxSpecialist`, moving it from `DRAFT` to the terminal `VOIDED` state; the same `VOIDED` fate befalls a draft or validated source-vendor return whose year-and-form key collides with a surviving return during a merge.

Corrections target accepted returns. A `TaxSpecialist` creates a correction against an original whose `federal_status` is `ACCEPTED`; correcting anything else, or correcting while another non-terminal correction of the same original exists, is rejected with `ERR_RETURN_NOT_CORRECTABLE`. The request is OCC-guarded per §2.8 and must carry `expected_return_version`; a version mismatch draws `ERR_STALE_VERSION`, and a successful correction increments the original return's `version` by one. The new return starts `DRAFT` with `is_correction` set to true, `corrects_return_id` naming the original, `box_amounts` recomputed on the final basis over the current ledger, and `provisional_box_amounts` initialized to that same final snapshot. The correction then walks the ordinary lifecycle — validation, seal, transmission — and at the moment it reaches `ACCEPTED`, the original named by `corrects_return_id` transitions from `ACCEPTED` to `SUPERSEDED` atomically in the same step.

### 3.7. Transmittals, E-File Thresholds, and Recipient Copy Delivery

A transmittal batches returns of one form type for one year. A `TaxSpecialist` creates it with `tax_year` and `form_type` (`NEC` or `MISC`; a transmittal carries exactly one form type), and creation fails with `ERR_NO_TAX_YEAR` when no tax-year row exists. The batch begins `OPEN`.

Sealing the batch, again a `TaxSpecialist` action, requires the transmittal to be `OPEN` (`ERR_INVALID_STATE_TRANSITION`) and at least one eligible return (`ERR_TRANSMITTAL_EMPTY`). Eligibility is exact: returns whose `federal_status` is `VALIDATED`, whose `tax_year` and `form_type` match the transmittal's, and whose `transmittal_id` is null. Eligible returns are considered in creation order, ascending — an observational ordering only, since every eligible return is taken. Each member return moves from `VALIDATED` to `TRANSMITTED`, has its `transmittal_id` set, and is recomputed to the final basis with `amount_basis` becoming `FINAL`; the transmittal's `return_count` records the member count and `sealed_by_user_id` records the caller. Only after the member transition does the system compute `filing_channel`: the qualifying count is the number of returns for the tax year whose `federal_status` is `VALIDATED`, `TRANSMITTED`, or `ACCEPTED`, and the recommended channel is `EFILE` when that count is at least the year's `efiling_threshold_count`, otherwise `PAPER`. Because the members are already `TRANSMITTED` when the count is taken, the count includes this transmittal's own returns — an intentional, pinned evaluation order.

A `TaxTransmitter` submits the sealed batch with a declared `channel`. The transmittal must be `SEALED`; the submitter must differ from `sealed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); no member return's vendor may have an `OPEN` `SECOND` B-notice (`ERR_UNRESOLVED_SECOND_B_NOTICE`); and a declared `PAPER` channel is accepted only when the qualifying count recomputed at submit time — the same three-step evaluation as at seal — is below the year's `efiling_threshold_count`, failing with `ERR_EFILE_REQUIRED` otherwise. An unrecognized `channel` is rejected with `ERR_INVALID_REQUEST`. A successful submit stamps `submitted_by_user_id` and moves the batch to `SUBMITTED`.

The IRS feed records the transmittal's `outcome` from `SUBMITTED` (`ERR_INVALID_STATE_TRANSITION` otherwise; unknown outcomes draw `ERR_INVALID_REQUEST`). An `ACCEPTED` outcome moves every member return to `ACCEPTED` — corrections superseding their originals atomically in the same step — and moves every state obligation for the same `tax_year` whose `required_channel` is `CFSF_FORWARD` and whose status is `PENDING` to `FILED_VIA_CFSF`. A `REJECTED` outcome returns every member to `VALIDATED` with its `transmittal_id` cleared. A `TaxSpecialist` may reopen a `REJECTED` transmittal, returning it to `OPEN` with `filing_channel`, `return_count`, and `sealed_by_user_id` reset to empty values.

Recipient copy delivery runs on a parallel status dimension, `recipient_copy_status`, which starts at `PENDING` and moves independently of the federal lifecycle. A `TaxSpecialist` delivers Copy B by naming a `channel`: `POSTAL` moves the copy status to `POSTAL_SENT`, and `ELECTRONIC` moves it to `E_DELIVERED` but only when the vendor's `e_delivery_consent` is true, failing with `ERR_ELECTRONIC_CONSENT_REQUIRED` otherwise. Either channel requires the return's `federal_status` to be `VALIDATED`, `TRANSMITTED`, or `ACCEPTED` (otherwise `ERR_INVALID_STATE_TRANSITION`) and the logical clock to read at or before the year's `recipient_copy_deadline` (otherwise `ERR_COPY_DEADLINE_PASSED`); an unrecognized channel draws `ERR_INVALID_REQUEST`. Each successful delivery stamps `copy_delivered_at` with the logical clock. When a postal copy comes back undeliverable, the `IRSSystem` bounce feed moves the copy status from `POSTAL_SENT` to `UNDELIVERABLE`, and from `UNDELIVERABLE` either channel may be attempted again under the same guards.

### 3.8. B-Notices and Backup Withholding Escalation

When the IRS mails a CP2100 notice, the `IRSSystem` feed records it as a B-notice carrying the `vendor_id` and the `notice_year` printed on the notice. The notice's `stage` is computed at creation and is `SECOND` when either of two conditions holds: another B-notice already exists for the same vendor whose `notice_year` falls within the closed interval from two years before the new notice's year through the new notice's year and which was created earlier than the new notice; or the vendor's `mismatch_count_3yr` is at least two at creation time. Otherwise the stage is `FIRST`; evaluation is chronological by creation order. Creation also escalates the vendor: the vendor's `b_notice_stage` becomes the higher of its current stage and the new notice's stage, with `NONE` ranking below `FIRST` and `FIRST` below `SECOND`, and when a `SECOND` notice lands the vendor's `backup_withholding_flag` is set and cannot subsequently be cleared by a W-9 match — the flag recomputation on a match keeps it true while any `SECOND` stage stands.

Resolving a notice requires it to be `OPEN`, and the path forks by stage. A `FIRST` notice — which either a `TaxSpecialist` or a `TaxAdmin` may resolve — requires the vendor's `tin_match_status` to be `MATCHED` by virtue of a W-9 submission created after the notice; anything else is rejected with `ERR_B_NOTICE_NOT_RESOLVABLE`. A `SECOND` notice may be resolved only by a `TaxAdmin` presenting `resolution_code` of `IRS_SSA_VALIDATION`; a `TaxSpecialist` may never resolve a `SECOND` notice, and any attempt missing the administrator role or the validation code is rejected with `ERR_B_NOTICE_NOT_RESOLVABLE`. Resolution stamps `resolved_by_user_id` with the caller, moves the notice to `RESOLVED`, recomputes the vendor's `b_notice_stage` as the highest stage among its remaining `OPEN` notices (`NONE` when none remain), and recomputes the `backup_withholding_flag` from the rule in §3.2. Notices can be listed with the `vendor_id` and `status` filters.

### 3.9. State Obligations and Duplicate Vendor Cleanup

State direct reporting is evaluated on demand by a `TaxSpecialist` naming a `tax_year` (with `ERR_NO_TAX_YEAR` when no tax-year row exists). The evaluation scans every `ACTIVE` vendor — `MERGED` and `DEACTIVATED` vendors are skipped — that has at least one `POSTED` in-year payment. For each such vendor, the governing rule is the state rule whose `state_code` equals the vendor's `address_state` and whose closed effective interval contains the evaluate-time logical clock — `effective_from` at or before the clock and `effective_to` at or after it; if several rules match, the one with the latest `effective_from` wins, a tie being impossible because overlapping rules are rejected at creation. When no rule matches, no obligation row is created for that vendor. The obligation's `reportable_amount_cents` is the sum of `amount_cents` over the vendor's `POSTED` in-year reportable payments across all boxes, NEC and MISC alike. Its `required_channel` is `CFSF_FORWARD` when the rule's `participates_in_cfsf` is true; otherwise `DIRECT_FILE` when `reportable_amount_cents` is at least the rule's `direct_reporting_threshold_cents`; otherwise `NOT_REQUIRED`. The obligation's status mirrors the channel: `CFSF_FORWARD` and `DIRECT_FILE` rows start `PENDING`, while a `NOT_REQUIRED` channel yields a `NOT_REQUIRED` status immediately. Re-evaluating an existing vendor-year obligation updates the row in place only while it is `PENDING`; terminal rows are left untouched, so a vendor merge or payment void that drops the total below the threshold flips a still-`PENDING` row to `NOT_REQUIRED` on the next evaluation. The response reports `evaluated_count`, the `created_obligation_ids` array, and `updated_count`. Obligations can be listed with the `vendor_id`, `state_rule_id`, `tax_year`, and `status` filters, and a `TaxSpecialist` discharges a direct-file duty by marking the obligation filed — valid only from `PENDING` and only when `required_channel` is `DIRECT_FILE`, otherwise `ERR_INVALID_STATE_TRANSITION` — which moves it to `FILED_DIRECT`. Obligations routed `CFSF_FORWARD` reach `FILED_VIA_CFSF` automatically when a transmittal for their year is accepted, per §3.7.

Duplicate vendor cleanup is a two-person workflow. An `APClerk` opens a merge request with `source_vendor_id` (the duplicate that will be merged away), `target_vendor_id` (the survivor), and a free-text `reason`; the caller is recorded as `requested_by_user_id`. Naming the same vendor on both sides is rejected at request time with `ERR_SELF_MERGE`, and unknown vendor ids draw `ERR_NOT_FOUND`. The request starts `PENDING` and can be listed or fetched with the `source_vendor_id`, `target_vendor_id`, and `status` filters.

Approval belongs to a `TaxAdmin` and is checked in order: the request must be `PENDING`; the approver, recorded as `reviewed_by_user_id`, must differ from `requested_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); source and target must be distinct (`ERR_SELF_MERGE`); both vendors must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`); their TINs must be equal and both non-null (`ERR_TIN_MISMATCH_ON_MERGE`); and the source must have no W-9 submission awaiting a match (`ERR_VENDOR_HAS_OPEN_OBLIGATIONS`). Approval executes the merge as one cascade, moving the request itself to the terminal `EXECUTED` state. The source vendor becomes `MERGED` with `merged_into_vendor_id` pointing at the target. Its payments are re-parented to the target — `vendor_id` rewritten, while `tax_year`, `is_reportable`, and `reportable_box` stay as frozen at posting. Its withholding entries move to the target, whose `withholding_balance_cents` is recomputed as the combined sum. Its B-notices move, and the target's `b_notice_stage` becomes the higher of the two vendors' stages under the `NONE`-then-`FIRST`-then-`SECOND` ordering. Its W-9 submissions other than those awaiting a match are re-parented. Its returns are re-parented as well — except that a source return in `DRAFT` or `VALIDATED` whose year-and-form key collides with an existing non-terminal target return is `VOIDED` instead of re-parented, and the target's own surviving `DRAFT` or `VALIDATED` returns are invalidated back to `DRAFT` with their box amounts recomputed. Finally, the source's state obligations are re-parented to the target. A `TaxAdmin` may instead reject a `PENDING` request, moving it to `REJECTED` with no further effect.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a tax year, vendor, W-9 submission, payment, remittance draft, generated return batch, correction return, transmittal, state rule, B-notice, or merge request — return a `201 Created` status code. Operations that modify an existing resource, record feed outcomes, or run evaluations return a `200 OK` status code. Readers must consult §3 for the request fields, guards, and cascades behind each operation; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tax1099/_clock/set_current_utc` | Advance the logical clock | TaxAdmin |
| POST | `/tax1099/tax-years` | Create a tax year configuration | TaxAdmin |
| POST | `/tax1099/tax-years/{taxYearId}/close` | Close a tax year | TaxAdmin |
| POST | `/tax1099/vendors` | Onboard a vendor | APClerk, TaxAdmin |
| GET | `/tax1099/vendors/{vendorId}` | Get a vendor (portal callers read their own id only) | APClerk, TaxAdmin, TaxSpecialist, VendorPortal |
| GET | `/tax1099/vendors` | List vendors with filters and pagination | APClerk, TaxAdmin, TaxSpecialist |
| PATCH | `/tax1099/vendors/{vendorId}` | Update vendor master data (OCC-guarded) | APClerk, TaxAdmin |
| POST | `/tax1099/vendors/{vendorId}/deactivate` | Deactivate a vendor with no open obligations | TaxAdmin |
| POST | `/tax1099/vendors/{vendorId}/w9-submissions` | Submit a W-9 for the vendor | APClerk, VendorPortal |
| GET | `/tax1099/w9-submissions/{submissionId}` | Get a single W-9 submission | APClerk, TaxAdmin, TaxSpecialist |
| GET | `/tax1099/w9-submissions` | List W-9 submissions | APClerk, TaxAdmin, TaxSpecialist |
| POST | `/tax1099/w9-submissions/{submissionId}/record-match-result` | Record the IRS TIN-match outcome | IRSSystem |
| POST | `/tax1099/payments` | Record a payment from any source system | APClerk |
| GET | `/tax1099/payments/{paymentId}` | Get a single payment | APClerk, TaxAdmin, TaxSpecialist |
| GET | `/tax1099/payments` | List payments | APClerk, TaxAdmin, TaxSpecialist |
| POST | `/tax1099/payments/{paymentId}/void` | Void a posted payment | APClerk, TaxAdmin |
| GET | `/tax1099/withholding-entries/{entryId}` | Get a single withholding ledger entry | APClerk, TaxAdmin, TaxSpecialist |
| GET | `/tax1099/withholding-entries` | List withholding ledger entries | APClerk, TaxAdmin, TaxSpecialist |
| POST | `/tax1099/withholding-entries/{entryId}/reverse` | Manually reverse an unremitted entry | TaxAdmin |
| POST | `/tax1099/remittances` | Draft a quarterly backup-withholding remittance | TaxSpecialist |
| GET | `/tax1099/remittances/{remittanceId}` | Get a remittance | TaxSpecialist, TaxAdmin, TaxTransmitter |
| POST | `/tax1099/remittances/{remittanceId}/submit` | Submit a draft remittance to the IRS | TaxTransmitter |
| POST | `/tax1099/remittances/{remittanceId}/record-outcome` | Record the IRS remittance outcome | IRSSystem |
| POST | `/tax1099/remittances/{remittanceId}/reopen` | Reopen a rejected remittance as draft | TaxSpecialist |
| POST | `/tax1099/returns/generate` | Bulk-generate draft returns for a tax year | TaxSpecialist |
| GET | `/tax1099/returns/{returnId}` | Get a return | TaxSpecialist, TaxAdmin |
| GET | `/tax1099/returns` | List returns | TaxSpecialist, TaxAdmin |
| POST | `/tax1099/returns/{returnId}/validate` | Validate a draft return | TaxSpecialist |
| POST | `/tax1099/returns/{returnId}/void` | Void an erroneous draft return | TaxSpecialist |
| POST | `/tax1099/returns/{returnId}/correct` | Create a correction against an accepted return (OCC-guarded) | TaxSpecialist |
| POST | `/tax1099/returns/{returnId}/deliver-copy` | Deliver recipient Copy B by postal or electronic channel | TaxSpecialist |
| POST | `/tax1099/returns/{returnId}/record-copy-bounce` | Record a postal copy returned undeliverable | IRSSystem |
| POST | `/tax1099/transmittals` | Create an open transmittal batch | TaxSpecialist |
| GET | `/tax1099/transmittals/{transmittalId}` | Get a transmittal | TaxSpecialist, TaxAdmin, TaxTransmitter |
| POST | `/tax1099/transmittals/{transmittalId}/seal` | Seal eligible validated returns and compute the channel | TaxSpecialist |
| POST | `/tax1099/transmittals/{transmittalId}/submit` | Submit a sealed transmittal with a declared channel | TaxTransmitter |
| POST | `/tax1099/transmittals/{transmittalId}/record-outcome` | Record the IRS transmittal outcome | IRSSystem |
| POST | `/tax1099/transmittals/{transmittalId}/reopen` | Reopen a rejected transmittal as open | TaxSpecialist |
| POST | `/tax1099/state-rules` | Create a state reporting rule | TaxAdmin |
| POST | `/tax1099/state-obligations/evaluate` | Compute or refresh per-vendor state obligations for a year | TaxSpecialist |
| GET | `/tax1099/state-obligations/{obligationId}` | Get a single state obligation | TaxSpecialist, TaxAdmin |
| GET | `/tax1099/state-obligations` | List state obligations | TaxSpecialist, TaxAdmin |
| POST | `/tax1099/state-obligations/{obligationId}/mark-filed` | Mark a direct-file obligation as filed | TaxSpecialist |
| POST | `/tax1099/b-notices` | Record an inbound IRS B-notice | IRSSystem |
| GET | `/tax1099/b-notices/{noticeId}` | Get a single B-notice | TaxSpecialist, TaxAdmin, IRSSystem |
| GET | `/tax1099/b-notices` | List B-notices | TaxSpecialist, TaxAdmin, IRSSystem |
| POST | `/tax1099/b-notices/{noticeId}/resolve` | Resolve an open B-notice | TaxSpecialist, TaxAdmin |
| POST | `/tax1099/vendor-merge-requests` | Request a duplicate-vendor merge | APClerk |
| POST | `/tax1099/vendor-merge-requests/{requestId}/approve` | Approve and execute a merge | TaxAdmin |
| POST | `/tax1099/vendor-merge-requests/{requestId}/reject` | Reject a pending merge request | TaxAdmin |
| GET | `/tax1099/vendor-merge-requests/{requestId}` | Get a single merge request | APClerk, TaxAdmin |
| GET | `/tax1099/vendor-merge-requests` | List merge requests | APClerk, TaxAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3; this catalogue is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_TIN_FORMAT` | 422 Unprocessable Entity |
| `ERR_W9_NOT_ON_FILE` | 409 Conflict |
| `ERR_VENDOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_VENDOR_HAS_OPEN_OBLIGATIONS` | 409 Conflict |
| `ERR_NO_TAX_YEAR` | 422 Unprocessable Entity |
| `ERR_TAX_YEAR_CLOSED` | 409 Conflict |
| `ERR_TAX_YEAR_OVERLAP` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_ENTRY_ALREADY_REMITTED` | 409 Conflict |
| `ERR_NOTHING_TO_REMIT` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_UNRESOLVED_SECOND_B_NOTICE` | 409 Conflict |
| `ERR_B_NOTICE_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_RETURN_NOT_CORRECTABLE` | 409 Conflict |
| `ERR_TRANSMITTAL_EMPTY` | 409 Conflict |
| `ERR_EFILE_REQUIRED` | 409 Conflict |
| `ERR_COPY_DEADLINE_PASSED` | 409 Conflict |
| `ERR_ELECTRONIC_CONSENT_REQUIRED` | 409 Conflict |
| `ERR_STATE_RULE_OVERLAP` | 409 Conflict |
| `ERR_SELF_MERGE` | 422 Unprocessable Entity |
| `ERR_TIN_MISMATCH_ON_MERGE` | 409 Conflict |
