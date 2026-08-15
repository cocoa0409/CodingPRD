# Foreclosure Trustee & Auction Administration API — Product Requirements Document

## 1. Introduction

A foreclosure trustee company sits at the center of one of the most heavily regulated workflows in consumer finance: administering non-judicial foreclosures on behalf of lenders and investors. The work begins when a beneficiary refers a defaulted loan and ends months later with either a cured loan or a completed trustee's auction, a recorded trustee's deed, and the distribution of any surplus sale proceeds. Every step is bounded by statute: recording a notice of default opens a fixed reinstatement period, a notice of trustee's sale must be advertised on a weekly cadence before any auction may be held, bidders must qualify against deposit thresholds, and surplus funds must be paid out in lien-priority order. Interwoven through all of this are the realities of practice — beneficiaries issue and revise bidding instructions, borrowers tender reinstatement or payoff amounts at the eleventh hour, bankruptcy petitions and litigation holds freeze sale-side activity without warning, and sales are postponed, voided, and rescheduled.

This document specifies a single REST API that governs that entire pipeline. The system tracks beneficiaries and their referred cases, records the statutory notices and publication runs, computes reinstatement and payoff quotes with pinned rounding semantics, qualifies third-party bidders and conducts the auction, applies sale proceeds through a defined disbursement waterfall, and administers surplus claims under segregation-of-duties controls. Two design commitments shape everything that follows. First, determinism: the server operates on a logical clock rather than wall-clock time, so every statutory deadline, gap rule, and expiry is reproducible. Second, auditability: money and state move only through recorded, reversible operations — disbursements can be reversed as compensating entries, a sold auction can be voided with a full accounting unwind, and every material transition increments a visible resource version so that writers acting on a stale view are refused rather than silently overwriting work they never saw.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, roles, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party acts. The system recognizes exactly five roles, spelled as follows: `TrusteeAdmin`, `CaseManager`, `Auctioneer`, `Beneficiary`, and `ThirdPartyBidder`. A request arriving without these headers, or carrying a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the caller is authenticated but the role is not among those permitted for the endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). The complete role-permission mapping for each operation appears in the endpoint table in Section 4.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `TrusteeAdmin`, `CaseManager`, or `Auctioneer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `filed_by_user_id` on a surplus claim — but does not compare it to any entity's `id`.

When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`; ownership checks on any resource that references a `Beneficiary` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Beneficiary`-role call that touches a specific case — reading the case itself, submitting or listing its bidding instructions, or submitting or listing its cost advances — requires the case's `beneficiary_id` to equal `X-User-ID`; otherwise the request is rejected with `ERR_BENEFICIARY_OWNERSHIP_MISMATCH` (HTTP 403). That enumeration is exhaustive: other `Beneficiary`-role reads touching a case — the computed summary, the quote and claim lists, and the notice lists — are not ownership-gated.

When `X-User-Role` is `ThirdPartyBidder`, `X-User-ID` is the `id` of the acting `BidderRegistration`. A third-party bidder placing a bid must present a payload whose `bidder_registration_id` equals the caller's `X-User-ID`; a mismatch is rejected with `ERR_BIDDER_OWNERSHIP_MISMATCH` (HTTP 403). A `ThirdPartyBidder` may read auction sales and bids, and may read only its own registration record.

Segregation of duties is enforced where a single operator could otherwise control both sides of a decision. In particular, the case manager who reviews a surplus claim must not be the same user who filed it; a review where the reviewer's `X-User-ID` equals the claim's `filed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Non-integer or out-of-range pagination values are never rejected: a non-integer `limit` falls back to 10 and a non-integer `offset` to 0, while out-of-bounds integers clamp to the nearest bound (`limit` to 1 or 100, `offset` to 0). Unless a more specific ordering is stated for a particular list, all list endpoints return resources sorted by `created_at` in ascending order, with ties on `created_at` broken by creation order — record identifiers are never used for ordering. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, with `has_more` true exactly when `offset + limit` is less than `total_count`.

### 2.4. Common Resource Properties and Versioning

Every primary resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` equals `created_at` at creation and changes whenever any property of the resource changes. The `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource, including mutations driven by cascades — when a case's `lifecycle_status` advances, when a computed field such as `undistributed_surplus_cents` is recomputed, or when a parent's counters are updated by a child event, the affected resource's `updated_at` refreshes and its `version` increments.

Two resources are deliberate exceptions to this rule because they are immutable ledger entries: a `Postponement` and a `Bid` are never modified after creation. Each carries only `id` and `created_at`; both `updated_at` and `version` are absent on these two resources.

### 2.5. The Logical Clock and Date Consistency

The server never reads wall-clock time for any domain evaluation. All temporal evaluation — statutory deadlines, gap rules, expiry surfaces, acceptance windows — is computed against a server-maintained logical clock; the sole wall-clock read in the system is the envelope's `api_request_timestamp`, which carries no business meaning. At startup, before any call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `TrusteeAdmin`-only test-driving capability sets the clock, forward or backward, to a supplied `to_iso8601` instant; the response reports the resulting `current_utc`. Caller-supplied datetime values (such as a sale's `scheduled_sale_start_at`, a postponement's `new_sale_start_at`, and a stay's `filed_at`) are stored verbatim as supplied and parsed on demand for every comparison; a system-computed start derived from a stored start — the stay auto-postponement of Section 3.7 — is rendered in the same style as the stored value. Advancing the clock fires no automatic sweeps: quote and claim expiry are derived lazily at read or acceptance time, as described in Section 3.

Several date-bearing inputs are checked against the logical clock as part of request validation, and violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400):

- The `recording_date` of a notice of default and the `recording_date` of a notice of trustee's sale must each not lie in the future relative to the logical clock; past dates and the current clock date are accepted.
- The `filed_date` of a surplus claim must equal the current logical-clock date.
- The `filed_at` timestamp of a stay order must not lie in the future.
- The `run_date` of a publication must not lie in the future.
- The `incurred_date` of a cost advance must not lie in the future.
- The `good_through_date` of a quote must be on or after the current logical-clock date.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are integer cents. Fields documented as requiring positive cents — the unpaid principal balance, the monthly payment, advance amounts, bid amounts, deposit amounts, claimed amounts, and instruction bid amounts — must be greater than zero; the contractual late charge per month may be zero. Wherever a calculation produces a fractional cent, the value is rounded half-up to whole cents. Two rounding-order rules are pinned and non-negotiable:

- Per-diem interest rounds the daily amount to whole cents first and only then multiplies by the day count. Rounding after multiplication is forbidden.
- Quote line items are each computed and rounded to integer cents first, and the quote total is a single sum of those six integer lines — plus, for a `PAYOFF` quote only, the full `unpaid_principal_balance_cents`, which enters the total without appearing in any of the six stored lines. Summing unrounded values and rounding the total is forbidden.

Date arithmetic throughout the system is performed in whole calendar days. Where a day count is taken between two dates, the start date is excluded and the end date is included; a window whose end precedes its start counts as zero days.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to present the version of a parent entity as it was last observed, protecting workflows where a new submission legitimately supersedes or amends prior work and a writer holding a stale view must be refused rather than displacing something it never saw. The version field is non-optional on these operations; no other endpoint accepts a version field.

- Issuing a quote against a case requires `expected_foreclosure_case_version` to match the case's current `version`. Because a new quote legitimately supersedes the prior issued quote of the same type, a client whose view of the case predates another writer's change is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) rather than silently superseding a quote it never observed.
- Submitting a bidding instruction against a case likewise requires `expected_foreclosure_case_version` to match the case's current `version`, with the same rejection — `ERR_STALE_CASE_VERSION` (HTTP 412) — guarding the supersession of the prior active instruction.
- Postponing an auction sale requires `expected_auction_sale_version` to match the sale's current `version`. Successive postponements are legitimate, so the only sound rejection basis is the staleness of the client's view of the sale; a mismatch is rejected with `ERR_STALE_SALE_VERSION` (HTTP 412).

### 2.8. Validation Order and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed order so the surfaced error is deterministic. The global precedence ladder is:

1. Header presence and role validity (`ERR_UNAUTHENTICATED`).
2. Role permission for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Caller-to-resource ownership (`ERR_BENEFICIARY_OWNERSHIP_MISMATCH`, `ERR_BIDDER_OWNERSHIP_MISMATCH`).
4. Path identifier existence, resolved left to right (`ERR_RESOURCE_NOT_FOUND`).
5. Request-body schema and clock consistency — required fields present, no unknown fields, valid enum values, positive integer cents where required, well-formed datetimes, uniqueness of `loan_reference` and `reference_code`, and the clock-consistency rules of Section 2.5 (`ERR_INVALID_REQUEST`).
6. Entity state checks (`ERR_INVALID_CASE_STATE`, `ERR_INVALID_NOTS_STATE`, `ERR_INVALID_SALE_STATE`, `ERR_INVALID_QUOTE_STATE`, `ERR_INVALID_REGISTRATION_STATE`, `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_DEED_STATE`, `ERR_INVALID_INSTRUCTION_STATE`, `ERR_STAY_NOT_ACTIVE`, `ERR_INVALID_DISBURSEMENT_STATE`).
7. Optimistic-concurrency staleness (`ERR_STALE_CASE_VERSION`, `ERR_STALE_SALE_VERSION`).
8. Business safety gates (`ERR_ACTIVE_STAY`, `ERR_SEGREGATION_OF_DUTIES`).
9. Business temporal, constraint, and fiscal rules (the remaining catalogue entries).

Within a single endpoint, the more specific orderings — for example, state before staleness before postponement limits — are stated alongside the workflow narratives in Section 3.

### 2.9. Nested Resource Retrieval

Requests that address nested resources resolve path identifiers strictly left to right. A path naming a case and then a child collection, or a child resource and then its own child, first confirms the leftmost identifier and proceeds rightward only while each identifier resolves; the first identifier that does not resolve aborts the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and no business validation runs against a resource whose ancestor did not resolve. Ownership checks are evaluated against resolved resources, so a caller who would fail an ownership check against an existing resource still receives `ERR_RESOURCE_NOT_FOUND` when the identifier itself does not resolve.

### 2.10. Hold Posture: Stays as a Compound Gate

Every case carries a computed `hold_status` derived from its stay-order children, independent of its `lifecycle_status`. The posture is `BANKRUPTCY_STAY` whenever any `ACTIVE` stay of a bankruptcy type exists on the case; otherwise `LITIGATION_HOLD` whenever any `ACTIVE` litigation-hold stay exists; otherwise `CLEAR`. The posture is recomputed whenever a stay is filed or released.

A case that is not `CLEAR` may not advance along its sale-side lifecycle. Five operations are gated this way and are rejected with `ERR_ACTIVE_STAY` (HTTP 409) while the case is under hold: recording a notice of default, recording a notice of trustee's sale, scheduling an auction, conducting an auction, and closing an auction. Cure-side and administrative work is deliberately not gated: quotes may be issued and accepted, bidding instructions submitted or withdrawn, and cost advances submitted or reviewed while a hold is in effect.

### 2.11. Funds Movement Integrity and Compensating Reversals

Every disbursement is created in `CLEARED` status; the only correction mechanism is a compensating reversal performed by a `TrusteeAdmin`, which moves the disbursement to `REVERSED` and restores the affected balances. The system maintains a funds-conservation invariant on every case whose sale has closed: the sum of `amount_cents` across that case's `CLEARED` disbursements of recipient type `CLAIMANT` or `BORROWER_RESIDUE`, plus the case's `undistributed_surplus_cents`, always equals the surplus computed at auction close. A disbursement paired with its reversal leaves this quantity unchanged, and the invariant is re-verified after every distribution run and every reversal.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Case Referral

A `TrusteeAdmin` onboards a beneficiary — the lender or investor that owns the defaulted loans — by supplying its legal `name`, a `reference_code` unique across all beneficiaries, and a `contact_email`. The new beneficiary begins in `ACTIVE` status. Suspension is a one-way administrative action: a `TrusteeAdmin` may move a beneficiary from `ACTIVE` to `SUSPENDED`, which increments the beneficiary's `version` and blocks the recording of any new notice of default on every case that beneficiary owns — such an attempt is rejected with `ERR_BENEFICIARY_SUSPENDED` (HTTP 422). A beneficiary in `SUSPENDED` status remains so; the system offers no reactivation path, and a suspend request against a beneficiary that is not `ACTIVE` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Each beneficiary also carries `total_outstanding_advances_cents`, a computed running total of the advanced costs the trustee has approved but not yet repaid: it is the sum of `amount_cents` over all cost advances in `APPROVED` status belonging to that beneficiary's cases, and it rises and falls as advances are approved, reimbursed, and unwound (see Sections 3.5 and 3.8).

Referral intake is performed by a `CaseManager`, who creates a foreclosure case against an existing beneficiary. The intake payload identifies the owning beneficiary through `beneficiary_id` — a value naming no existing beneficiary is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) — and captures the loan as referred: `loan_reference` (unique across all cases), `borrower_name`, `property_address`, and `county_code` for the recording jurisdiction. The financial picture is captured through `unpaid_principal_balance_cents` and `monthly_payment_cents` (both positive integer cents), `months_in_arrears` (a count of full missed monthly payments, at least one), `late_fee_per_month_cents` (the contractual late charge per missed month, zero or more), `note_rate_pct` (the annual note interest rate in percent, such as 7.2; accepted as any JSON number, with no range constraint), and `last_interest_paid_date` (the date through which interest is paid; payoff interest accrues from the day after). Two elections are recorded at intake: `prepayment_penalty_applies`, a boolean defaulting to `false` that controls whether payoff quotes carry the prepayment penalty, and `distribution_method`, which selects the surplus waterfall variant — `STATUTORY_PRIORITY` or `PRO_RATA` — and is immutable once the case is created.

A case is born in `REFERRED` with `hold_status` of `CLEAR`, `undistributed_surplus_cents` of zero, and no `reinstatement_deadline_date`. Over its life the case's `lifecycle_status` walks some prefix of `REFERRED`, `NOD_RECORDED`, `NOTS_RECORDED`, `SALE_SCHEDULED`, `SOLD`, and `DEED_RECORDED`, and terminates in exactly one of `CLOSED`, `REINSTATED`, `PAID_OFF`, or `CANCELLED`; a backward edge from `SOLD` to `NOTS_RECORDED` (the sale-void rewind of Section 3.8) and a forced rewind from `SALE_SCHEDULED` to `NOD_RECORDED` (the stay overflow of Section 3.7) are the only moves that run counter to that direction. Cases may be listed with optional `beneficiary_id` and `lifecycle_status` filters plus the standard pagination parameters. A computed summary read of a case returns its current posture and statutory aggregates: `lifecycle_status`, `hold_status`, `active_stay_count`, `reinstatement_deadline_date`, `reinstatement_cutoff_date`, `claims_deadline_date`, `undistributed_surplus_cents`, and `total_approved_costs_cents` (the sum of `amount_cents` over the case's `APPROVED` cost advances). The summary's three date fields are recomputed on each read rather than echoed from stored fields: `reinstatement_deadline_date` derives from the case's currently `RECORDED` notice of default and is null when none exists, `reinstatement_cutoff_date` is null while no sale in `SCHEDULED` or `CONDUCTED` status exists, and `claims_deadline_date` is null while no `CLOSED` sale exists.

### 3.2. The Notice of Default and the Reinstatement Window

Recording the notice of default is the first statutory act. A `CaseManager` records it against a case by supplying the `recording_date` and the county recorder's `instrument_number`; the recording date must not lie in the future relative to the logical clock. The recording is permitted only when the case is still `REFERRED`, the case's `hold_status` is `CLEAR`, and the beneficiary is `ACTIVE` — and the checks are evaluated in that order, so a case under an active stay surfaces `ERR_ACTIVE_STAY` rather than `ERR_BENEFICIARY_SUSPENDED` even when the beneficiary is also suspended, while a case that has already moved past referral fails first with `ERR_INVALID_CASE_STATE` (HTTP 409). On success the system creates a `NoticeOfDefault` in `RECORDED` status with `rescinded_at` still null, advances the case to `NOD_RECORDED`, sets the case's `reinstatement_deadline_date` to ninety days after the recording date, and increments the case's `version`. The notices of default recorded on a case can be listed at any time.

The ninety days following the recording date are the borrower's statutory reinstatement window. During it the borrower may cure the default by accepting a reinstatement quote (Section 3.6), and the trustee may not yet record the notice of trustee's sale: such a recording attempted before the clock date reaches `reinstatement_deadline_date` is rejected with `ERR_NOTS_TOO_EARLY` (HTTP 422), with recording on the deadline day itself permitted.

Rescission unwinds the filing. A `CaseManager` may rescind a notice of default that is still `RECORDED` while the case sits in `NOD_RECORDED`, `NOTS_RECORDED`, or `SALE_SCHEDULED` — the case-state check runs first and surfaces `ERR_INVALID_CASE_STATE`, while a notice that is no longer `RECORDED` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); the notice's `status` becomes `RESCINDED`, its `rescinded_at` is stamped, and the case moves to `CANCELLED`. The cascade beyond the notice depends on how far the case had progressed, and each branch is fully specified:

- From `NOD_RECORDED`: the notice is rescinded, every `ISSUED` quote on the case becomes `VOIDED`, and the case becomes `CANCELLED`.
- From `NOTS_RECORDED`: the notice is rescinded; additionally, the case's notice of trustee's sale in `RECORDED` or `PUBLICATION_COMPLETE` status becomes `VOIDED`, every `ISSUED` quote becomes `VOIDED`, and the case becomes `CANCELLED`.
- From `SALE_SCHEDULED`: the notice is rescinded; additionally, the notice of trustee's sale in `SALE_SCHEDULED` status becomes `VOIDED`, the scheduled auction sale becomes `VOIDED`, every `QUALIFIED` bidder registration becomes `REFUND_PENDING`, the `ACTIVE` bidding instruction becomes `EXPIRED`, every `ISSUED` quote becomes `VOIDED`, and the case becomes `CANCELLED`.

In all three branches the case's `version` increments once for the transition. Throughout these cascades — and the identical sale-voiding cascade of the quote-acceptance paths in Section 3.6 — "the scheduled auction sale" denotes a sale in `SCHEDULED` status; a sale already `CONDUCTED` is left untouched. A case in `CANCELLED` is terminal; nothing further may be recorded or accepted against it.

### 3.3. The Notice of Trustee's Sale and the Publication Cycle

Once the reinstatement window has run, a `CaseManager` records the notice of trustee's sale by supplying its `recording_date` and `instrument_number`; again the recording date must not lie in the future relative to the logical clock. Recording requires the case to be in `NOD_RECORDED` with `hold_status` of `CLEAR`, the clock date to be on or after the `reinstatement_deadline_date` (exactly on the deadline day is allowed), a `RECORDED` notice of default to exist on the case, and no other notice of trustee's sale in `RECORDED`, `PUBLICATION_COMPLETE`, or `SALE_SCHEDULED` status to exist on the case — a case carries at most one live trustee's-sale notice at a time. State-driven rejections on this operation surface as `ERR_INVALID_CASE_STATE`, while the premature-recording rejection is `ERR_NOTS_TOO_EARLY`. A successful recording creates the notice in `RECORDED` status with `postponement_count` at zero and `first_publication_date` still null, moves the case to `NOTS_RECORDED`, and increments the case's `version`. A case's notices of trustee's sale may be listed, and an individual notice may be read by its identifier.

Statute requires the sale to be advertised weekly. A `CaseManager` records each advertisement run against the notice by supplying the `run_date` and the `newspaper_name` of the newspaper of general circulation; each run is stamped with a `run_index`, a one-based sequence number assigned in creation order within the parent notice. Three rules govern publication recording, evaluated after the request schema checks (including the requirement that `run_date` not lie in the future, which surfaces as `ERR_INVALID_REQUEST`): first the notice itself must be in `RECORDED` or `PUBLICATION_COMPLETE` status, failing which the request is rejected with `ERR_INVALID_NOTS_STATE`; then the run date must fall at least seven days after the most recent sibling run — a run exactly seven days later is acceptable — failing which the rejection is `ERR_PUBLICATION_GAP_VIOLATION` (HTTP 422); finally, a notice accepts at most three publication runs, and a fourth attempt is rejected with `ERR_PUBLICATION_LIMIT` (HTTP 422). The notice's `first_publication_date` is maintained as the earliest `run_date` among its publication children and remains null until the first run is recorded. A notice's publications may be listed.

Each recorded run proceeds from `RUN` to `AFFIDAVIT_FILED` when a `CaseManager` files the affidavit of publication. Filing evaluates three checks in order: the publication must still be in `RUN` status, failing which the rejection is `ERR_INVALID_REQUEST` (HTTP 400); then the parent notice must be in `RECORDED` or `PUBLICATION_COMPLETE` status, failing which the rejection is `ERR_INVALID_NOTS_STATE`; then the clock date must be on or after the run's `run_date`, failing which the rejection is `ERR_INVALID_REQUEST`. On filing, `affidavit_filed_at` is stamped. When the third publication child reaches `AFFIDAVIT_FILED` — exactly three runs, all with affidavits filed — the parent notice bubbles up from `RECORDED` to `PUBLICATION_COMPLETE` automatically, with `first_publication_date` already in place from the runs themselves.

### 3.4. Cost Advances and the Beneficiary Ledger

Beneficiaries front the out-of-pocket costs of the foreclosure and recover them later. A `Beneficiary` caller submits a cost advance against one of its own cases, supplying a `category` — one of `PUBLICATION`, `RECORDING`, `POSTING`, `LEGAL`, `PROPERTY_PRESERVATION`, or `OTHER` — the `amount_cents` advanced (positive integer cents), and the `incurred_date` on which the cost was incurred. The submission stamps `submitted_by_beneficiary_id` from the caller's `X-User-ID` and creates the advance in `SUBMITTED` status. Submission requires the case to be in a non-terminal lifecycle status; an attempt on a case that is `CLOSED`, `REINSTATED`, `PAID_OFF`, or `CANCELLED` is rejected with `ERR_INVALID_CASE_STATE`. A case's advances may be listed with an optional `status` filter.

Review is the trustee's gate. A `CaseManager` reviews a `SUBMITTED` advance with a `decision` of `APPROVE` or `DENY`; reviewing an advance in any other status is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Approval additionally requires the case to still be in a non-terminal status (`ERR_INVALID_CASE_STATE` otherwise), and moves the advance to `APPROVED`: the advance's `version` increments, and the owning beneficiary's `total_outstanding_advances_cents` increases by the advance's `amount_cents`. Denial requires a non-empty `denial_reason` — a missing or empty reason is rejected with `ERR_INVALID_REQUEST` — which is recorded on the advance as it moves to `DENIED`. Both `DENIED` and `REIMBURSED` are terminal.

Reimbursement is always a cascade, never a direct action. An advance moves from `APPROVED` to `REIMBURSED` when a payoff quote covering the case is accepted (Section 3.6) or when a closing auction creates the advance's cost-reimbursement disbursement (Section 3.8); in both cases the beneficiary's `total_outstanding_advances_cents` decreases by the advance's amount. Should the closed sale later be voided, every advance that sale's close had reimbursed returns from `REIMBURSED` to `APPROVED`, and the beneficiary's outstanding total rises by the same amounts again — the reimbursement is unwound because the proceeds that funded it no longer exist.

### 3.5. Bidding Instructions from the Beneficiary

Before an auction can be conducted, the beneficiary must tell the trustee how to bid. A `Beneficiary` caller submits a bidding instruction against one of its own cases with an `opening_bid_cents` (the opening credit bid, positive integer cents), a `max_bid_cents` (the maximum authorized bid, positive integer cents), and a `strategy` of either `OPENING_ONLY` or `UP_TO_MAX`. Submission is accepted only while the case is in `NOTS_RECORDED` or `SALE_SCHEDULED` — earlier there is nothing to instruct against, and later the instruction can no longer change; a case in any other status rejects the submission with `ERR_INVALID_CASE_STATE`. The instruction's own consistency rule requires `opening_bid_cents` not to exceed `max_bid_cents`; a violation is rejected with `ERR_OPENING_BID_EXCEEDS_MAX` (HTTP 422).

Because a new instruction legitimately supersedes the prior one, submission is optimistic-concurrency protected as described in Section 2.7: the payload must carry `expected_foreclosure_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_CASE_VERSION`. The checks run in a fixed order — caller ownership first, then case state, then version staleness, then the opening-bid ceiling. On success the prior `ACTIVE` instruction on the case, if any, becomes `SUPERSEDED`, the new instruction begins in `ACTIVE` status, and the case's `version` increments. A case's instructions may be listed with an optional `status` filter.

A beneficiary may withdraw its `ACTIVE` instruction, moving it to `WITHDRAWN`, provided the case is in `NOTS_RECORDED` or `SALE_SCHEDULED` and no auction sale of the case is currently in `CONDUCTED` status — the instruction is locked from the moment the auctioneer cries the sale. The checks run in a fixed order: the instruction must still be `ACTIVE` (`ERR_INVALID_INSTRUCTION_STATE`, HTTP 409), then the case must be in `NOTS_RECORDED` or `SALE_SCHEDULED` (`ERR_INVALID_CASE_STATE`), then the conducted-sale lock (`ERR_INVALID_SALE_STATE`, HTTP 409). Two further transitions are pure cascades: when a sale on the case closes, the `ACTIVE` instruction is consumed and becomes `EXECUTED`; and when the case reaches `REINSTATED`, `PAID_OFF`, or `CANCELLED`, any `ACTIVE` instruction becomes `EXPIRED`. Instruction activity is never blocked by a stay hold.

### 3.6. Quotes: Issuance, Variants, and Acceptance

A quote fixes, in writing, the exact amount that will cure the default or retire the loan if tendered by a stated date. A `CaseManager` issues a quote against a case by supplying the `quote_type` — `REINSTATEMENT` or `PAYOFF` — and the `good_through_date` through which the quoted figures hold. Issuance requires the case to be in a non-terminal status (`ERR_INVALID_CASE_STATE` otherwise), and because a new quote of the same type legitimately supersedes the prior issued one, the payload must carry `expected_foreclosure_case_version` matching the case's current `version` — the case-state check runs first, then the staleness check, and a stale writer is rejected with `ERR_STALE_CASE_VERSION`. On success, the prior `ISSUED` quote of the same `quote_type` on the case becomes `SUPERSEDED`, the new quote is created in `ISSUED` status with all six line items computed and stored, and the case's `version` increments. Quotes may be listed with optional `quote_type` and `status` filters; the `status` filter matches the surfaced (derived) status, so `status=EXPIRED` selects stored-`ISSUED` quotes whose `good_through_date` has passed.

Every quote carries the same six line items, all integer cents, each rounded before the total is summed:

- `arrears_cents` — for a `REINSTATEMENT` quote, the `monthly_payment_cents` multiplied by `months_in_arrears`; for a `PAYOFF` quote, zero.
- `late_fees_cents` — for `REINSTATEMENT`, the `late_fee_per_month_cents` multiplied by `months_in_arrears`; for `PAYOFF`, zero.
- `costs_cents` — for both variants, the sum of `amount_cents` over the case's cost advances in `APPROVED` status at issuance; advances in `SUBMITTED`, `DENIED`, or `REIMBURSED` status are excluded.
- `interest_cents` — for `REINSTATEMENT`, per-diem interest on the sum of the arrears and late-fees lines, accruing from the recording date of the case's `RECORDED` notice of default through the `good_through_date` (zero when the case has no `RECORDED` notice of default, as on a `REFERRED` case); for `PAYOFF`, per-diem interest on the `unpaid_principal_balance_cents`, accruing from the `last_interest_paid_date` through the `good_through_date`.
- `trustee_fee_cents` — a flat five hundred dollars (50000 cents) for `REINSTATEMENT`, a flat two hundred fifty dollars (25000 cents) for `PAYOFF`.
- `prepayment_penalty_cents` — for `PAYOFF` only, when the case's `prepayment_penalty_applies` is true: two percent of the `unpaid_principal_balance_cents`, rounded half-up to whole cents; otherwise zero.

Per-diem interest, wherever it is used, is computed identically: the daily amount in cents is the base in cents multiplied by the `note_rate_pct`, divided by one hundred, divided by three hundred sixty-five, and rounded half-up to whole cents; that rounded daily amount is then multiplied by the number of calendar days in the accrual window, counting from the day after the start date through the end date inclusive. The `total_cents` of the quote is the single sum of the six line items as integer cents, plus — for a `PAYOFF` quote only — the full `unpaid_principal_balance_cents`: a payoff retires the loan, so the tendered total must also cover the principal even though no line item carries it (`arrears_cents` remains zero for `PAYOFF`).

A quote's `EXPIRED` status is derived, never stored. While the stored status remains `ISSUED`, any read of the quote — and any acceptance attempt — made when the clock date has passed the `good_through_date` surfaces the status as `EXPIRED`. Acceptance of such a quote fails with `ERR_QUOTE_EXPIRED` (HTTP 422), not with a state error: `ERR_INVALID_QUOTE_STATE` (HTTP 409) is reserved for acceptance attempts on quotes whose stored status is already terminal — `ACCEPTED`, `SUPERSEDED`, or `VOIDED`.

Acceptance records the borrower's tender and is the pivot on which the case turns. A `CaseManager` accepts an `ISSUED` quote by presenting the `tendered_amount_cents` actually received. Five checks run in order: the case must be in a status that permits the acceptance for the quote's type (`ERR_INVALID_CASE_STATE`); the quote's stored status must be `ISSUED` (`ERR_INVALID_QUOTE_STATE`); the clock date must not have passed the `good_through_date` (`ERR_QUOTE_EXPIRED`); for a `REINSTATEMENT` quote with a sale pending, the reinstatement cutoff must not have passed (`ERR_REINSTATEMENT_CUTOFF_PASSED`, HTTP 422); and the tendered amount must equal the quote's `total_cents` exactly — a tender even one cent short or one cent over is rejected with `ERR_PAYMENT_SHORTFALL` (HTTP 422). On acceptance the quote becomes `ACCEPTED`, its `accepted_at` is stamped, and the case transitions according to the quote type, incrementing the case's `version`.

The reinstatement cutoff deserves precision: when an auction sale in `SCHEDULED` or `CONDUCTED` status exists on the case, a reinstatement may be accepted only while the clock date is on or before the date five business days before the scheduled sale date, computed by walking backward from the sale date one calendar day at a time and counting only Monday through Friday — weekends are skipped, and no holiday calendar is applied. Acceptance on the cutoff day itself is allowed. When no such sale exists, no cutoff applies.

Accepting a `REINSTATEMENT` quote moves the case to `REINSTATED` from any of `NOD_RECORDED`, `NOTS_RECORDED`, or `SALE_SCHEDULED`, with the cascade growing as the case had progressed:

- From `NOD_RECORDED`: the `RECORDED` notice of default becomes `RESCINDED`, and the case becomes `REINSTATED`.
- From `NOTS_RECORDED`: the `RECORDED` notice of default becomes `RESCINDED`; additionally, the notice of trustee's sale in `RECORDED` or `PUBLICATION_COMPLETE` status becomes `VOIDED`, and the case becomes `REINSTATED`.
- From `SALE_SCHEDULED`: the `RECORDED` notice of default becomes `RESCINDED`; additionally, the notice of trustee's sale in `SALE_SCHEDULED` status becomes `CONCLUDED`, the scheduled auction sale becomes `VOIDED`, every `QUALIFIED` bidder registration becomes `REFUND_PENDING`, the `ACTIVE` bidding instruction becomes `EXPIRED`, and the case becomes `REINSTATED`.

Accepting a `PAYOFF` quote moves the case to `PAID_OFF` from any of `REFERRED`, `NOD_RECORDED`, `NOTS_RECORDED`, or `SALE_SCHEDULED`, and every payoff acceptance reimburses the beneficiary's costs inside the payoff: all of the case's cost advances in `APPROVED` status become `REIMBURSED` (decrementing the beneficiary's outstanding-advances total accordingly), and every other `ISSUED` quote on the case becomes `VOIDED`. The remaining cascade again grows with the case's progress:

- From `REFERRED`: the cost advances are reimbursed, the other issued quotes are voided, and the case becomes `PAID_OFF`.
- From `NOD_RECORDED`: additionally, the `RECORDED` notice of default becomes `RESCINDED`.
- From `NOTS_RECORDED`: additionally, the `RECORDED` notice of default becomes `RESCINDED`, and the notice of trustee's sale in `RECORDED` or `PUBLICATION_COMPLETE` status becomes `VOIDED`.
- From `SALE_SCHEDULED`: additionally, the `RECORDED` notice of default becomes `RESCINDED`, the notice of trustee's sale in `SALE_SCHEDULED` status becomes `CONCLUDED`, the scheduled auction sale becomes `VOIDED`, every `QUALIFIED` bidder registration becomes `REFUND_PENDING`, and the `ACTIVE` bidding instruction becomes `EXPIRED`.

Whichever terminal status a case reaches — `REINSTATED`, `PAID_OFF`, or `CANCELLED` — any quote still `ISSUED` on the case at that moment becomes `VOIDED`, and any instruction still `ACTIVE` becomes `EXPIRED`.

### 3.7. Bankruptcy and Litigation Stays

A bankruptcy petition or a court-ordered litigation hold freezes the sale side of a case without ending it. A `CaseManager` files a stay order against a case in any non-terminal status — filing on a terminal case is rejected with `ERR_INVALID_CASE_STATE` — supplying the `stay_type` (`BANKRUPTCY_CHAPTER_7`, `BANKRUPTCY_CHAPTER_11`, `BANKRUPTCY_CHAPTER_13`, or `LITIGATION_HOLD`), the `court_case_number`, and the `filed_at` filing timestamp, which must not lie in the future. The stay is created in `ACTIVE` status with `released_at` and `release_court_order_reference` still null, the case's `hold_status` is recomputed per Section 2.10, and the case's `version` increments. A case's stay orders may be listed with an optional `status` filter.

Filing a stay has a mechanical side effect when a sale is waiting. If an auction sale of the case is in `SCHEDULED` status at the moment the stay is filed, the system postpones that sale automatically: the sale's start moves to exactly thirty days after its currently scheduled start, a system-created `Postponement` records the move with its `reason` set to `BANKRUPTCY_STAY` for any bankruptcy stay type or `OPERATION_OF_LAW` for a litigation hold and its `announced_via` set to `ADVANCE`, and this automatic postponement consumes one of the notice's three postponements exactly as a manual one would. When the notice's `postponement_count` has already reached three, no further postponement is possible; the forced fourth postponement instead voids the machinery — the `SCHEDULED` sale becomes `VOIDED`, the notice of trustee's sale becomes `VOIDED`, and the case rewinds from `SALE_SCHEDULED` to `NOD_RECORDED`, requiring the trustee to re-notice the sale from scratch.

A stay is released when the court permits. A `CaseManager` releases an `ACTIVE` stay by supplying a non-empty `release_court_order_reference`; a release attempted on a stay that is no longer `ACTIVE` is rejected with `ERR_STAY_NOT_ACTIVE` (HTTP 409). On release the stay becomes `RELEASED`, `released_at` is stamped, the supplied reference is recorded, the case's `hold_status` is recomputed — returning to `CLEAR` when the released stay was the last `ACTIVE` one — and the case's `version` increments. Release lifts the gate described in Section 2.10; it does not rewind the automatic postponement, which stands as recorded.

### 3.8. From Scheduling to the Fall of the Hammer

#### Scheduling the sale

With publication complete, a `CaseManager` schedules the auction against a notice of trustee's sale by supplying the `venue_name` and the `scheduled_sale_start_at` (an ISO 8601 UTC instant). The guards run in a fixed order: first the case must be in `NOTS_RECORDED` (`ERR_INVALID_CASE_STATE`); then the notice's own state must permit scheduling (`ERR_INVALID_NOTS_STATE`); then the case's `hold_status` must be `CLEAR` (`ERR_ACTIVE_STAY`); then the notice must have completed its publication cycle — scheduling against a notice that has not reached `PUBLICATION_COMPLETE` is rejected with `ERR_PUBLICATION_INCOMPLETE` (HTTP 422); then the scheduled start must be at least twenty days after the notice's `first_publication_date` and at least fourteen days after the notice's `recording_date` — starts on either boundary day are acceptable, and a violation is rejected with `ERR_SALE_DATE_TOO_SOON` (HTTP 422); and the venue must be free. A sale occupies its venue for a half-open interval of sixty minutes beginning at its start — the start instant itself is occupied, the instant exactly sixty minutes later is not — and a schedule attempt conflicts, surfacing `ERR_AUCTION_SCHEDULE_CONFLICT` (HTTP 409), whenever another sale with the same `venue_name` in `SCHEDULED` or `CONDUCTED` status has an occupancy interval intersecting the requested one; two sales where one ends exactly as the other begins do not conflict. On success the system creates the `AuctionSale` in `SCHEDULED` status carrying the sale's `foreclosure_case_id`, `notice_of_trustee_sale_id`, `venue_name`, and `scheduled_sale_start_at`, with every outcome field — `opening_bid_cents`, `winner_type`, `winning_bid_cents`, `winning_bidder_registration_id`, `total_debt_at_close_cents`, and `closed_at` — still null; the notice moves to `SALE_SCHEDULED`; the case moves to `SALE_SCHEDULED`; and the case's `version` increments. Sales may be listed with optional `notice_of_trustee_sale_id`, `foreclosure_case_id`, and `status` filters, and read individually.

#### Postponements

An `Auctioneer` may postpone a `SCHEDULED` sale — and only a `SCHEDULED` sale, with other statuses rejected as `ERR_INVALID_SALE_STATE` — by supplying the `new_sale_start_at`, a `reason` of `BENEFICIARY_REQUEST`, `TRUSTEE_DISCRETION`, `MUTUAL_AGREEMENT`, `OPERATION_OF_LAW`, or `BANKRUPTCY_STAY`, and an `announced_via` of `ADVANCE` or `AT_SALE`. Because postponements may legitimately stack, the request must carry `expected_auction_sale_version` matching the sale's current `version`; a stale view is rejected with `ERR_STALE_SALE_VERSION`. After the state and staleness checks, three business rules apply in order: the venue-conflict rule is re-evaluated at the new start under the same sixty-minute half-open occupancy (`ERR_AUCTION_SCHEDULE_CONFLICT`); the parent notice's `postponement_count` must still be below three — the third postponement is allowed and the fourth is rejected with `ERR_POSTPONEMENT_LIMIT` (HTTP 422); and the new start must be strictly later than the currently scheduled start and no more than thirty days after it, with a start exactly thirty days out permitted — otherwise `ERR_POSTPONEMENT_WINDOW` (HTTP 422). On success the system creates an immutable `Postponement` recording the `auction_sale_id`, the `prior_sale_start_at` captured before the move, the `new_sale_start_at`, the `reason`, and the `announced_via`; the sale's `scheduled_sale_start_at` is updated; the notice's `postponement_count` increments by one; and the sale's `version` increments. A sale's postponements may be listed.

#### Bidder registration and qualification

Third-party bidders register per sale. An `Auctioneer` registers a bidder against a sale by supplying the `bidder_name`, `bidder_email`, and the `deposit_cents` tendered by cashier's check (positive integer cents); registration requires the sale to be in `SCHEDULED` or `CONDUCTED` status — any other status is rejected with `ERR_INVALID_SALE_STATE` — and the registration is created in `PENDING` status with `required_deposit_cents` still null (it is computed and recorded at a qualifying review). The auctioneer then reviews each registration with a `decision` of `QUALIFY` or `DISQUALIFY`.

Qualification is the deposit gate. Reviewing a registration that is not `PENDING` — or, for bids and refunds, one in the wrong status — surfaces `ERR_INVALID_REGISTRATION_STATE` (HTTP 409). To qualify, the registration must be `PENDING`, the sale must be in `SCHEDULED` or `CONDUCTED` status (`ERR_INVALID_SALE_STATE` otherwise), and the tendered `deposit_cents` must be at least the registration's `required_deposit_cents` — meeting the requirement exactly qualifies — with a shortfall rejected as `ERR_DEPOSIT_INSUFFICIENT` (HTTP 422); the sale-state check runs before the registration-state check, and the deposit test runs last. The required deposit is computed at review time: the opening reference is the `opening_bid_cents` of the case's `ACTIVE` bidding instruction if one exists, and otherwise the case's `unpaid_principal_balance_cents`; the `required_deposit_cents` is the greater of ten thousand dollars (1000000 cents) and one percent of the opening reference rounded half-up to whole cents.

Disqualification always requires a non-empty `reason` — a missing or empty reason is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — which is recorded as the registration's `disqualification_reason` as the registration moves to `DISQUALIFIED`, a terminal status. From `PENDING`, disqualification is unconditional. From `QUALIFIED`, disqualification is permitted only while the registration has placed no bid on the sale and the sale has not reached `CLOSED` — a registration that has already bid, or whose sale has closed, cannot be disqualified after the fact: the already-bid attempt, like an attempt on a registration in any status other than `PENDING` or `QUALIFIED`, is rejected with `ERR_INVALID_REGISTRATION_STATE`, while the closed sale is caught earlier by the sale-state gate (`ERR_INVALID_SALE_STATE`). Three further registration transitions are cascades rather than direct actions: when the sale closes, the winning registration moves from `QUALIFIED` to `DEPOSIT_APPLIED` and every other `QUALIFIED` registration moves to `REFUND_PENDING`; a voided sale and a case terminal transition likewise push `QUALIFIED` registrations — or the winner's `DEPOSIT_APPLIED` registration, in the void case — to `REFUND_PENDING`. Finally, an `Auctioneer` refunds a `REFUND_PENDING` registration, releasing the deposit and moving it to `REFUNDED`; no other field changes. Registrations may be listed per sale with an optional `status` filter, and read individually — a `ThirdPartyBidder` caller being limited to its own registration `id`.

#### Conducting the sale and taking bids

On the day of the sale, an `Auctioneer` conducts the auction. Conducting requires the sale to be `SCHEDULED` (`ERR_INVALID_SALE_STATE`), the case to be in `SALE_SCHEDULED` with `hold_status` of `CLEAR` (`ERR_ACTIVE_STAY`), an `ACTIVE` bidding instruction to exist on the case (without one the sale cannot be cried and the attempt is rejected with `ERR_NO_ACTIVE_BIDDING_INSTRUCTION`, HTTP 422), and the current clock UTC date to equal the calendar date of the sale's `scheduled_sale_start_at` — an attempt on any other day is rejected with `ERR_SALE_NOT_TODAY` (HTTP 422). The checks run in a fixed order: sale state (`ERR_INVALID_SALE_STATE`), then case state — the case must be in `SALE_SCHEDULED`, failing which the rejection is `ERR_INVALID_CASE_STATE` — then hold posture (`ERR_ACTIVE_STAY`), then the instruction requirement, then the calendar match. Conducting snapshots the `opening_bid_cents` from the `ACTIVE` instruction onto the sale — the snapshot is fixed at that instant even if the instruction is later superseded — moves the sale to `CONDUCTED`, and increments the sale's `version`.

While the sale is `CONDUCTED`, qualified bidders bid. A `ThirdPartyBidder` places a bid with a payload naming its `bidder_registration_id` and the `amount_cents` offered; the caller's `X-User-ID` must equal the payload's `bidder_registration_id` (`ERR_BIDDER_OWNERSHIP_MISMATCH`). Four checks then run in order: the sale must be `CONDUCTED` (`ERR_INVALID_SALE_STATE`); the registration must be `QUALIFIED` — a payload naming a registration that does not exist, belongs to a different sale, or is in any other status is rejected with `ERR_INVALID_REGISTRATION_STATE`; and the amount must meet the minimum next bid — a bid exactly at the minimum is accepted, and anything lower is rejected with `ERR_BID_TOO_LOW` (HTTP 422). The minimum is computed from the bidding so far: the increment over a base amount is the greater of five hundred dollars (50000 cents) and one-half of one percent of that base rounded half-up to whole cents. When no bid has yet been placed on the sale, the base is the sale's `opening_bid_cents` and the first bid must be at least the opening bid plus the increment over it; thereafter the base is the current highest accepted bid, and each new bid must be at least that high bid plus the increment over it. An accepted bid is an immutable record carrying the `auction_sale_id`, the `bidder_registration_id`, the `amount_cents`, and a server-stamped `placed_at`; bids are never edited or deleted. The bids of a sale may be listed in `placed_at` ascending order (ties broken by creation order), and the bids placed under a single registration may be listed as well.

#### Closing the sale

Closing is the auction's moment of truth and the system's largest single transaction. An `Auctioneer` closes a sale when the case is in `SALE_SCHEDULED`, the sale is in `CONDUCTED` status, and the case's `hold_status` is `CLEAR` — the case-state, sale-state, and hold checks run in that order, surfacing `ERR_INVALID_CASE_STATE`, `ERR_INVALID_SALE_STATE`, and `ERR_ACTIVE_STAY` respectively.

Winner determination looks only at bids whose registration is `QUALIFIED` at the moment of close; bids from registrations disqualified after bidding are excluded from consideration. When no qualifying bid exists, the beneficiary takes the property: `winner_type` becomes `BENEFICIARY` and `winning_bid_cents` becomes the sale's `opening_bid_cents` — the credit bid — with `winning_bidder_registration_id` left null. When qualifying bids exist, the winner is the highest bid by `amount_cents`, with ties broken in favor of the earliest `placed_at`; record identifiers are never used for ordering. The sale then records `winner_type` of `THIRD_PARTY`, the winning amount in `winning_bid_cents`, and the winner's registration in `winning_bidder_registration_id`.

The trustee's compensation is computed at close. The fee base is the `winning_bid_cents` when a third party wins and the `total_debt_at_close_cents` when the beneficiary wins; the fee itself is one-half of one percent of the base rounded half-up to whole cents, bounded below by seven hundred fifty dollars (75000 cents) and above by four thousand seven hundred fifty dollars (475000 cents). The `total_debt_at_close_cents` is the case's `unpaid_principal_balance_cents` plus per-diem interest on that principal accruing from the `last_interest_paid_date` through the close date — the logical-clock UTC date at the moment of close — computed under the per-diem rule of Section 3.6.

Proceeds are then applied in a fixed order, each step drawing down the sale proceeds before any surplus is measured, and each step creating a `CLEARED` disbursement: first a `TRUSTEE_FEE` disbursement for the compensation fee; then one `BENEFICIARY_COST_REIMBURSEMENT` disbursement per `APPROVED` cost advance, taken in the advances' `created_at` ascending order, with each covered advance moving to `REIMBURSED` (and the beneficiary's outstanding-advances total falling accordingly); then a `BENEFICIARY_DEBT_PAYOFF` disbursement for the lesser of the remaining proceeds and the `total_debt_at_close_cents`, created only when that lesser amount is positive — a zero-or-negative remainder produces no debt-payoff disbursement. Every disbursement the close creates carries `distribution_run_index` zero (run numbering is reserved for the distribution runs of Section 3.9) and a null `surplus_claim_id`. The surplus is what remains: the `winning_bid_cents` minus the total obligations — the trustee fee, the sum of the approved advances, and the total debt at close — floored at zero when the bid does not cover the obligations. The case's `undistributed_surplus_cents` is set to that surplus.

Close then settles the room: the sale becomes `CLOSED` with `closed_at` stamped; the parent notice of trustee's sale becomes `CONCLUDED`; the case moves to `SOLD` and its `version` increments; the `ACTIVE` bidding instruction becomes `EXECUTED`; and registrations settle — the winner's `QUALIFIED` registration becomes `DEPOSIT_APPLIED`, and every other `QUALIFIED` registration becomes `REFUND_PENDING`, awaiting refund.

#### Voiding the sale

A sale that should not have happened can be unwound. An `Auctioneer` voids a sale, supplying a non-empty `reason`, while the sale is in `CONDUCTED` or `CLOSED` status — other statuses are rejected as `ERR_INVALID_SALE_STATE`. Two conditions make a sale un-voidable, surfacing `ERR_SALE_NOT_VOIDABLE` (HTTP 409): a trustee's deed in `RECORDED` status already exists for the sale, or surplus distribution has begun — that is, any disbursement of recipient type `CLAIMANT` or `BORROWER_RESIDUE` exists for the case. A conducted-but-not-yet-closed sale may be voided on the day of the sale, before close.

The void is a full compensation unwind. The sale becomes `VOIDED`; a trustee's deed still in `DRAFTED` status for the sale becomes `VOIDED`; the winner's `DEPOSIT_APPLIED` registration returns to `REFUND_PENDING`; every `CLEARED` proceeds-application disbursement created by this sale's close — the `TRUSTEE_FEE`, each `BENEFICIARY_COST_REIMBURSEMENT`, and the `BENEFICIARY_DEBT_PAYOFF` — becomes `REVERSED`; every cost advance that close had set to `REIMBURSED` returns to `APPROVED`, restoring the beneficiary's outstanding-advances total; the case's `undistributed_surplus_cents` returns to zero; the parent notice of trustee's sale falls back from `SALE_SCHEDULED` (a conducted-not-closed void) or `CONCLUDED` (a closed-sale void) to `PUBLICATION_COMPLETE` — the publications remain valid, making the notice immediately re-schedulable; and the case moves back to `NOTS_RECORDED` (from `SOLD` after a closed-sale void, from `SALE_SCHEDULED` after a conducted-but-unclosed void), its `version` incrementing. This backward edge is the sale-retry cycle: a case may pass from `NOTS_RECORDED` through `SALE_SCHEDULED` and `SOLD` and back to `NOTS_RECORDED` more than once before the deed finally records.

### 3.9. Trustee's Deeds, Surplus Claims, and Distribution

#### Conveying title

Once a sale has closed, a `CaseManager` drafts the trustee's deed against the closed sale. A sale carries at most one live deed: the sale-state check runs first — a sale that is not `CLOSED` yields `ERR_INVALID_SALE_STATE` — and drafting is then rejected with `ERR_INVALID_DEED_STATE` (HTTP 409) when a deed in any status other than `VOIDED` already exists for the sale. The deed is created in `DRAFTED` status with `recorded_at` null, and its `grantee_name` is computed from the outcome — the winning bidder's name when the sale's `winner_type` is `THIRD_PARTY`, or the beneficiary's name when the winner is `BENEFICIARY`. A sale's deeds may be listed.

Recording the deed against the county completes the transfer. A `CaseManager` records a deed while the deed is in `DRAFTED` status (`ERR_INVALID_DEED_STATE` otherwise) and the case is in `SOLD` (`ERR_INVALID_CASE_STATE` otherwise); the deed-state check runs first, then the case-state check, and both run before the deadline test. The deadline is instant-level: the recording must occur at or before the instant exactly fifteen days after the sale's `closed_at` — unless the request carries `court_order_extension` set to true, in which case the deadline is waived; a late recording without the extension is rejected with `ERR_DEED_RECORDING_LATE` (HTTP 422). On recording, the deed becomes `RECORDED` with `recorded_at` stamped, the case moves to `DEED_RECORDED`, and the case's `version` increments. A deed whose sale is voided before recording becomes `VOIDED` by cascade, as Section 3.8 describes.

#### Surplus claims

When a sale produces surplus, parties with an interest in the proceeds file claims. A `CaseManager` files a surplus claim against a case while the case is in `SOLD` or `DEED_RECORDED` — filing on a case in any other status is rejected with `ERR_INVALID_CASE_STATE` — supplying the `claimant_name`, the `claimant_type` (`JUNIOR_LIENHOLDER`, `BORROWER`, or `JUDGMENT_CREDITOR`), the `priority_rank` (the lien priority tier, where 1 is senior-most and lower numbers pay first; any integer is accepted as a tier label), the `claimed_amount_cents` (positive integer cents), and the `filed_date`. The claims window is one hundred eighty days from the sale's close: the `filed_date` must equal the current clock date and must be no later than one hundred eighty days after the calendar date of the sale's `closed_at` — a filing exactly on the hundred-eightieth day is acceptable, and a filing past the deadline is rejected with `ERR_CLAIMS_DEADLINE_PASSED` (HTTP 422); the case-state check runs before the deadline check. The filing stamps `filed_by_user_id` from the caller's `X-User-ID` — the segregation-of-duties anchor — and creates the claim in `FILED` status with `approved_amount_cents` null, `paid_cents` at zero, and `denial_reason` null. A case's claims may be listed with an optional `status` filter; the filter matches the surfaced (derived) status.

Review separates the filer from the decider. A `CaseManager` reviews a claim that is in `FILED` status — anything else is rejected with `ERR_INVALID_CLAIM_STATE` (HTTP 409) — and the reviewer's `X-User-ID` must differ from the claim's `filed_by_user_id`; a self-review is rejected with `ERR_SEGREGATION_OF_DUTIES` before any decision is examined. The `FILED` test reads the surfaced (derived) status, so an expired claim is rejected with `ERR_INVALID_CLAIM_STATE` like any other non-`FILED` claim; no case-state gate applies at review time. An `APPROVE` decision sets the claim's `approved_amount_cents` to the supplied value, which must be an integer greater than zero and no more than the `claimed_amount_cents` — a missing or out-of-range value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and moves the claim to `APPROVED`. A `DENY` decision requires a non-empty `denial_reason` — a missing or empty reason is rejected with `ERR_INVALID_REQUEST` — which is recorded as the claim moves to `DENIED`.

Like a quote, a claim's `EXPIRED` status is derived rather than stored: a claim still in `FILED` status when the clock date has passed the claims deadline — one hundred eighty days after the closing sale's `closed_at` — surfaces as `EXPIRED` on any read. Expired claims drop out of the distribution input set entirely.

#### The distribution waterfall

Distribution pays the surplus out in lien order. A `CaseManager` invokes a distribution run against the case; a run with nothing to do — no `undistributed_surplus_cents`, no approved claims awaiting payment, and no borrower-residue work — is rejected with `ERR_NO_DISTRIBUTABLE_SURPLUS` (HTTP 422), unless that run would perform the final reconciliation close described below, which is permitted even when it creates no disbursements; and a run attempted on a case in any status other than `SOLD` or `DEED_RECORDED` — whether not yet sold, cured, cancelled, or already `CLOSED` — is rejected with `ERR_INVALID_CASE_STATE`. Each run is numbered by a one-based `distribution_run_index` on every disbursement it creates, numbered per case in run order (a rejected run consumes no index), and the run's response summarizes the work: the `run_index`, the `created_disbursement_count`, the `distributed_cents` paid out, the remaining `undistributed_surplus_cents`, and the resulting `case_status`.

The eligible set for a run is the case's claims in `APPROVED` status whose `paid_cents` is still below their `approved_amount_cents`; claims in `FILED`, `DENIED`, `EXPIRED`, or fully `PAID` status are excluded. Claims are processed tier by tier in `priority_rank` ascending order — tier 1 first — and the tier pool is the full remaining surplus when the run enters the tier: a tier is either fully satisfied, or the run ends with the surplus exhausted inside that tier. What happens within a tier depends on the case's `distribution_method`:

- Under `STATUTORY_PRIORITY`, claims within the tier are paid in strict filing order — earliest `created_at` first, never ordered by record identifier — each receiving the lesser of its unpaid approved amount and the remaining surplus. An early large claim can starve later same-tier claims entirely.
- Under `PRO_RATA`, claims within the tier split the tier pool proportionally — when the pool covers the tier's total unpaid approved amount there is nothing to split, and each claim in the tier is paid its full unpaid approved amount; otherwise each claim's share is the tier pool multiplied by the claim's unpaid approved amount and divided by the tier's total unpaid approved amount, rounded down to whole cents. The leftover cents — always fewer than the number of claims in the tier — are then distributed one cent at a time in `created_at` ascending order until exhausted. Identical inputs yield different per-claim payouts under the two variants.

Every payment creates a disbursement of recipient type `CLAIMANT` naming the claim through `surplus_claim_id`, increases the claim's `paid_cents` by the amount paid, and decreases the case's `undistributed_surplus_cents` by the same. A claim whose `paid_cents` reaches its `approved_amount_cents` becomes `PAID`.

The borrower stands last in line. When a run finds no eligible approved claims remaining and `undistributed_surplus_cents` is still positive — and either the claims window has closed (the clock date has passed one hundred eighty days after the close, computed on calendar dates) or no claims in any non-terminal status exist on the case — non-terminal here meaning `APPROVED` or `FILED`-and-not-`EXPIRED`, so `DENIED`, `PAID`, and derived-`EXPIRED` claims never block the residue — the run creates a single disbursement of recipient type `BORROWER_RESIDUE` for the full remainder.

The final reconciliation pass closes the file: when a run invoked on a case in `DEED_RECORDED` leaves `undistributed_surplus_cents` at zero and no claim in `FILED` (derived-`EXPIRED` aside) or `APPROVED` status remains, the case moves to `CLOSED` and its `version` increments. `CLOSED` is terminal.

#### Reversing a disbursement

Corrections to money already moved go through a compensating reversal, never an edit. A `TrusteeAdmin` reverses a disbursement that is in `CLEARED` status — a disbursement in any other status is rejected with `ERR_INVALID_DISBURSEMENT_STATE` (HTTP 409) — by supplying a non-empty `reversal_reason`, and only while the case has not yet reached `CLOSED`, after which the books are final and an attempt surfaces `ERR_INVALID_CASE_STATE`; the case-`CLOSED` check runs before the disbursement-state check. The disbursement becomes `REVERSED` and its `version` increments; the compensating effects depend on the recipient type. Reversing a `CLAIMANT` disbursement reduces the linked claim's `paid_cents` by the amount, and if the claim's `paid_cents` thereby falls below its `approved_amount_cents`, the claim regresses from `PAID` back to `APPROVED`. Reversing a `CLAIMANT` or `BORROWER_RESIDUE` disbursement also restores the case's `undistributed_surplus_cents` by the amount. Reversing a `BENEFICIARY_COST_REIMBURSEMENT` disbursement is accounting-only: the covered cost advance remains `REIMBURSED`. Reversing a `TRUSTEE_FEE` or `BENEFICIARY_DEBT_PAYOFF` disbursement is likewise accounting-only, changing nothing beyond the disbursement itself. The funds-conservation invariant of Section 2.11 holds across every such reversal. Disbursements may be listed with optional `foreclosure_case_id`, `surplus_claim_id`, and `recipient_type` filters, and read individually.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone resource such as a beneficiary or case, or a new member of a parent-owned collection such as a notice, publication, quote, stay order, instruction, postponement, registration, bid, deed, claim, or advance — return `201 Created`. Operations that act on an existing resource without creating a new one (transitions, reviews, acceptances, releases, refunds, reversals, distribution runs, reads, and lists) return `200 OK`. All responses use the envelope of Section 2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/beneficiaries` | Onboard a beneficiary client | TrusteeAdmin |
| GET | `/api/beneficiaries/{id}` | Read a beneficiary | TrusteeAdmin, CaseManager |
| POST | `/api/beneficiaries/{id}/suspend` | Suspend a beneficiary; its cases cannot record new notices of default | TrusteeAdmin |
| POST | `/api/foreclosure-cases` | Referral intake; creates a case in `REFERRED` | CaseManager |
| GET | `/api/foreclosure-cases` | List cases with filters and pagination | TrusteeAdmin, CaseManager, Auctioneer |
| GET | `/api/foreclosure-cases/{id}` | Read a case; Beneficiary callers must own it | TrusteeAdmin, CaseManager, Auctioneer, Beneficiary |
| GET | `/api/foreclosure-cases/{id}/summary` | Computed read: posture, statutory deadlines, aggregates | TrusteeAdmin, CaseManager, Beneficiary |
| POST | `/api/foreclosure-cases/{id}/notices-of-default` | Record the notice of default (`REFERRED` to `NOD_RECORDED`) | CaseManager |
| GET | `/api/foreclosure-cases/{id}/notices-of-default` | List notices of default of a case | TrusteeAdmin, CaseManager, Auctioneer, Beneficiary |
| POST | `/api/notices-of-default/{id}/rescind` | Rescind the notice of default; cascades the case to `CANCELLED` | CaseManager |
| POST | `/api/foreclosure-cases/{id}/notices-of-trustee-sale` | Record the notice of trustee's sale (`NOD_RECORDED` to `NOTS_RECORDED`); blocked before the reinstatement deadline | CaseManager |
| GET | `/api/foreclosure-cases/{id}/notices-of-trustee-sale` | List trustee's-sale notices of a case | TrusteeAdmin, CaseManager, Auctioneer, Beneficiary |
| GET | `/api/notices-of-trustee-sale/{id}` | Read a notice of trustee's sale | TrusteeAdmin, CaseManager, Auctioneer, Beneficiary |
| POST | `/api/notices-of-trustee-sale/{id}/publications` | Record a weekly publication run (maximum three; seven-day gaps) | CaseManager |
| GET | `/api/notices-of-trustee-sale/{id}/publications` | List publications of a notice | TrusteeAdmin, CaseManager, Auctioneer |
| POST | `/api/publications/{id}/file-affidavit` | File the affidavit of publication; the third affidavit completes the notice's publication cycle | CaseManager |
| POST | `/api/notices-of-trustee-sale/{id}/schedule-sale` | Schedule the auction; creates the sale in `SCHEDULED` | CaseManager |
| GET | `/api/auction-sales` | List auction sales with filters | TrusteeAdmin, CaseManager, Auctioneer, ThirdPartyBidder |
| GET | `/api/auction-sales/{id}` | Read an auction sale | TrusteeAdmin, CaseManager, Auctioneer, ThirdPartyBidder |
| POST | `/api/foreclosure-cases/{id}/cost-advances` | Beneficiary submits a cost advance in `SUBMITTED` status | Beneficiary |
| GET | `/api/foreclosure-cases/{id}/cost-advances` | List cost advances of a case | TrusteeAdmin, CaseManager, Beneficiary |
| POST | `/api/cost-advances/{id}/review` | Review an advance: approve or deny | CaseManager |
| POST | `/api/foreclosure-cases/{id}/quotes` | Issue a reinstatement or payoff quote; supersedes the prior issued quote of the same type (optimistic concurrency on the case version) | CaseManager |
| GET | `/api/foreclosure-cases/{id}/quotes` | List quotes of a case | TrusteeAdmin, CaseManager, Beneficiary |
| POST | `/api/quotes/{id}/accept` | Record a borrower tender equal to the quote total; drives the case to `REINSTATED` or `PAID_OFF` | CaseManager |
| POST | `/api/foreclosure-cases/{id}/stay-orders` | File a bankruptcy or litigation stay; recomputes hold posture and auto-postpones a scheduled sale (overflow voids the notice) | CaseManager |
| GET | `/api/foreclosure-cases/{id}/stay-orders` | List stay orders of a case | TrusteeAdmin, CaseManager, Beneficiary |
| POST | `/api/stay-orders/{id}/release` | Release a stay with a court order reference | CaseManager |
| POST | `/api/foreclosure-cases/{id}/bidding-instructions` | Beneficiary submits bidding instructions; supersedes the prior active instruction (optimistic concurrency on the case version) | Beneficiary |
| GET | `/api/foreclosure-cases/{id}/bidding-instructions` | List bidding instructions of a case | TrusteeAdmin, CaseManager, Auctioneer, Beneficiary |
| POST | `/api/bidding-instructions/{id}/withdraw` | Beneficiary withdraws an active instruction | Beneficiary |
| POST | `/api/auction-sales/{id}/postponements` | Postpone a scheduled sale (maximum three per notice; thirty-day window; optimistic concurrency on the sale version) | Auctioneer |
| GET | `/api/auction-sales/{id}/postponements` | List postponements of a sale | TrusteeAdmin, CaseManager, Auctioneer |
| POST | `/api/auction-sales/{id}/bidder-registrations` | Register a third-party bidder for a sale | Auctioneer |
| GET | `/api/auction-sales/{id}/bidder-registrations` | List registrations of a sale | TrusteeAdmin, CaseManager, Auctioneer |
| GET | `/api/bidder-registrations/{id}` | Read a registration (ThirdPartyBidder limited to its own) | TrusteeAdmin, CaseManager, Auctioneer, ThirdPartyBidder |
| POST | `/api/bidder-registrations/{id}/review` | Qualify or disqualify a registration; the deposit threshold is enforced | Auctioneer |
| POST | `/api/auction-sales/{id}/bids` | Place a bid while the sale is conducted; the minimum increment is enforced | ThirdPartyBidder |
| GET | `/api/auction-sales/{id}/bids` | List bids of a sale in `placed_at` ascending order | TrusteeAdmin, CaseManager, Auctioneer, ThirdPartyBidder |
| GET | `/api/bidder-registrations/{id}/bids` | List bids placed under a registration | TrusteeAdmin, CaseManager, Auctioneer, ThirdPartyBidder |
| POST | `/api/auction-sales/{id}/conduct` | Open the auction on its scheduled date; snapshots the opening bid | Auctioneer |
| POST | `/api/auction-sales/{id}/close` | Close the auction; winner determination, proceeds allocation, case to `SOLD` | Auctioneer |
| POST | `/api/auction-sales/{id}/void` | Void a conducted or closed sale (rewind to `NOTS_RECORDED`) | Auctioneer |
| POST | `/api/auction-sales/{id}/trustees-deeds` | Draft the trustee's deed to the winner (sale must be closed) | CaseManager |
| GET | `/api/auction-sales/{id}/trustees-deeds` | List deeds of a sale (zero or one active) | TrusteeAdmin, CaseManager |
| POST | `/api/trustees-deeds/{id}/record` | Record the deed within fifteen days of close (or with a court-order extension) | CaseManager |
| POST | `/api/foreclosure-cases/{id}/surplus-claims` | File a surplus-funds claim (within the claims window) | CaseManager |
| GET | `/api/foreclosure-cases/{id}/surplus-claims` | List claims of a case | TrusteeAdmin, CaseManager, Beneficiary |
| POST | `/api/surplus-claims/{id}/review` | Approve (with an approved amount) or deny a claim; the reviewer must differ from the filer | CaseManager |
| POST | `/api/foreclosure-cases/{id}/distribute-surplus` | Run the surplus waterfall; creates disbursements; the final pass closes the case | CaseManager |
| GET | `/api/disbursements` | List disbursements with filters | TrusteeAdmin, CaseManager, Beneficiary |
| GET | `/api/disbursements/{id}` | Read a disbursement | TrusteeAdmin, CaseManager |
| POST | `/api/disbursements/{id}/reverse` | Reverse a cleared disbursement (compensating action) | TrusteeAdmin |
| POST | `/api/bidder-registrations/{id}/refund` | Refund a losing or voided bidder's deposit | Auctioneer |
| POST | `/_clock/set_current_utc` | Test-driving logical clock; sets the server clock (startup default is exactly `2026-08-01T00:00:00Z`, never wall-clock) | TrusteeAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are specified in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_BENEFICIARY_OWNERSHIP_MISMATCH` | 403 |
| `ERR_BIDDER_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_CASE_STATE` | 409 |
| `ERR_INVALID_NOTS_STATE` | 409 |
| `ERR_INVALID_SALE_STATE` | 409 |
| `ERR_INVALID_QUOTE_STATE` | 409 |
| `ERR_INVALID_REGISTRATION_STATE` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_INVALID_DEED_STATE` | 409 |
| `ERR_INVALID_INSTRUCTION_STATE` | 409 |
| `ERR_INVALID_DISBURSEMENT_STATE` | 409 |
| `ERR_STAY_NOT_ACTIVE` | 409 |
| `ERR_ACTIVE_STAY` | 409 |
| `ERR_SALE_NOT_VOIDABLE` | 409 |
| `ERR_AUCTION_SCHEDULE_CONFLICT` | 409 |
| `ERR_NOTS_TOO_EARLY` | 422 |
| `ERR_PUBLICATION_GAP_VIOLATION` | 422 |
| `ERR_PUBLICATION_LIMIT` | 422 |
| `ERR_PUBLICATION_INCOMPLETE` | 422 |
| `ERR_SALE_DATE_TOO_SOON` | 422 |
| `ERR_POSTPONEMENT_LIMIT` | 422 |
| `ERR_POSTPONEMENT_WINDOW` | 422 |
| `ERR_QUOTE_EXPIRED` | 422 |
| `ERR_REINSTATEMENT_CUTOFF_PASSED` | 422 |
| `ERR_PAYMENT_SHORTFALL` | 422 |
| `ERR_NO_ACTIVE_BIDDING_INSTRUCTION` | 422 |
| `ERR_OPENING_BID_EXCEEDS_MAX` | 422 |
| `ERR_DEPOSIT_INSUFFICIENT` | 422 |
| `ERR_BID_TOO_LOW` | 422 |
| `ERR_CLAIMS_DEADLINE_PASSED` | 422 |
| `ERR_DEED_RECORDING_LATE` | 422 |
| `ERR_SALE_NOT_TODAY` | 422 |
| `ERR_NO_DISTRIBUTABLE_SURPLUS` | 422 |
| `ERR_BENEFICIARY_SUSPENDED` | 422 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_STALE_SALE_VERSION` | 412 |
