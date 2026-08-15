# Freelance Journalist Assignment Payment API — Product Requirements Document

## 1. Introduction

A publication's freelance desk runs on a fragile choreography of spreadsheets, email threads, and ad-hoc payment runs. Commissioning editors promise rates over lunch, contributors chase invoices months after filing, and finance discovers at year-end that a foreign contributor never filed a W8BEN. This document specifies the Freelance Desk API, a single service that owns the full lifecycle from contributor onboarding through assignment, verification, invoicing, batch settlement, and ledger posting.

The system is built around two convictions. First, money must be traceable: every cent that moves from the publication to a contributor flows through an explicit state machine, is captured in an immutable ledger, and is reconciled against a year-to-date gross figure that drives tax-reporting flags. Second, duties must be segregated: the person who verifies an invoice may not approve it, the person who locks a payment batch may not release it, and the person who records a plagiarism flag may not adjudicate it. The API enforces these separations mechanically, so the desk can scale without relying on trust.

Readers implementing this service should treat §2 as the structural contract (envelopes, pagination, concurrency, cross-cutting principles), §3 as the business narrative (state machines, calculations, and validation triggers woven into the workflows they guard), §4 as the endpoint index, and §5 as the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers. `X-User-ID` identifies the acting user; `X-User-Role` names the role under which they act. The role set is fixed: `DeskAdmin`, `Editor`, `Contributor`, `FinanceUser`, `VerificationEditor`. A request whose `X-User-Role` is absent or does not match one of these spellings, or whose `X-User-ID` is absent, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among the authorized roles for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

Identity semantics differ across roles. When `X-User-Role` is `Contributor`, `X-User-ID` is the `id` of the acting `Contributor`; ownership checks on any resource that references a `Contributor` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `DeskAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `locked_by_user_id` on `PaymentBatch` where a lock transition writes it) but does not compare it to any entity's `id`. The same opaque form applies when `X-User-Role` is `Editor`, when it is `FinanceUser`, and when it is `VerificationEditor`: in each case `X-User-ID` is an operator identifier that may be stamped onto resources (such as `submitted_by_contributor_id` on `Invoice`, or the recorder/adjudicator identities compared by segregation-of-duties checks) but is never resolved against an entity `id`.

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

List endpoints accept two query parameters. `limit` controls page size: it defaults to 10, has a minimum of 1, and a maximum of 100. `offset` controls how many records to skip and defaults to 0. Responses include the four pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Unless a more specific ordering is stated for a particular endpoint, list results are sorted by `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every persisted entity carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC values with three fractional digits. Any mutation of an entity refreshes its `updated_at` and increments its `version` by one. `LedgerEntry` is the single exception: it carries `id` and `created_at` only; `updated_at` and `version` are absent because postings are immutable.

Two write operations are guarded by optimistic concurrency control. Creating a rate agreement against a contributor requires the request to carry `expected_contributor_version`, the contributor `version` the client last observed; if it does not match the contributor's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Releasing a payment batch likewise requires `expected_batch_version` matching the batch's current `version`, with the same rejection code and status on mismatch. Endpoints not named in this paragraph do not take a version field.

### 2.5. The Logical Clock

All temporal reasoning in the desk — deadline lateness, tax-document expiry, due dates, late fees, year-to-date windows — is driven by a single logical clock rather than wall-clock time. At server startup the clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. A `DeskAdmin` may advance it via a test-driving capability that takes a `to_iso8601` timestamp and returns the new `now_utc`. Advancing the clock triggers a sweep: every `TaxDocument` whose `status` is `VERIFIED` and whose `expires_at` is earlier than the new now transitions to `EXPIRED`, and subsequent withholding computations for that contributor resolve to the punitive branch.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents. Calculations that divide (kill-fee percentages, withholding basis points, late fees, reuse royalties, rights uplift) use floor division — any fractional cent is discarded, never rounded half-up. Percentages are expressed either as a plain numerator over 100 (kill fee, reuse royalty, uplift) or as basis points over 10,000 (withholding rates, late-fee accrual, verification similarity thresholds). The reconstruction rule for every formula in §3 is: evaluate in the pinned order, use floor division at each integer division, and never round to two decimals because inputs are already cents.

### 2.7. Hierarchical Path Validation and Cross-Aggregate Cascades

Nested paths are validated left-to-right: each path-templated resource must exist before any child resource is resolved, and a missing id at any level yields `ERR_NOT_FOUND`. When a parent transitions in a way that invalidates children, the cascade is part of the transition's contract: terminating a contributor supersedes their active agreements and kills their not-yet-accepted assignments; confirming a plagiarism violation voids the payment dimension, denies open expenses, reverts rights, and suspends the contributor. §3 spells out each cascade alongside the workflow that triggers it.

### 2.8. Segregation of Duties

Three pairwise separations are enforced mechanically, all keyed on `X-User-ID`. The `FinanceUser` who verifies an invoice may not approve it. The `FinanceUser` whose identifier was recorded in `locked_by_user_id` when a batch was locked may not release that batch. The `VerificationEditor` who recorded a flag on a verification report may not adjudicate that same report. Violating any of the three yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Roster Management and Tax Residency

A `DeskAdmin` adds a freelance journalist to the roster with their `legal_name` (used for tax reporting), an optional `pen_name` byline (empty string when not supplied), a contact `email`, a `tax_residency` class, and an optional `backup_withholding_flag` (defaulting to false). Email uniqueness is enforced case-insensitively across the entire roster: a duplicate submission is rejected with `ERR_DUPLICATE_EMAIL`. `tax_residency` takes one of two values, `DOMESTIC_US` or `FOREIGN`, and is immutable once a `VERIFIED` tax document exists for the contributor.

A new contributor starts in `ACTIVE` status. Suspension by a `DeskAdmin` moves them to `SUSPENDED`, refreshing `updated_at` and bumping `version`; while suspended, no new assignment may be offered to them. Reinstatement moves `SUSPENDED` back to `ACTIVE`. Termination — allowed from either `ACTIVE` or `SUSPENDED` — moves the contributor to `TERMINATED` and cascades downward: every rate agreement still `ACTIVE` for the contributor flips to `SUPERSEDED`, and every assignment still in `DRAFT` or `OFFERED` is killed with `kill_fee_tier` set to `PRE_DELIVERY` and its final fee computed by the kill-variant rule (§3.4).

Each contributor accumulates two computed fields. `ytd_gross_cents` is the calendar-year-to-date sum of gross fee, expense, late-fee, and reuse-royalty ledger credits posted for the contributor (see §3.8 for the exact aggregation). `reportable_threshold_crossed` flips to true once `ytd_gross_cents` reaches the desk's `reporting_threshold_cents` (default 60000 cents, i.e. $600); the comparison is inclusive, so a contributor whose year-to-date gross lands exactly on the threshold is flagged.

### 3.2. Rate Agreements and the Supersede Pattern

Commissioning terms live on `RateAgreement` records owned by a contributor. An agreement declares a `pricing_mode` — either `PER_WORD` or `FLAT` — and exactly one of the two rate fields: `per_word_rate_cents` (at least 1) when the mode is `PER_WORD`, or `flat_fee_cents` (at least 1) when the mode is `FLAT`; the non-applicable field must be null. It also carries a `kill_fee_pct_num` between 1 and 100, a `rights_default` of `FIRST`, `ONE_TIME`, or `ALL`, and a validity window from `effective_from` (inclusive) to `effective_to` (exclusive, null for open-ended).

At most one agreement per contributor is `ACTIVE` at any time. Creating a new agreement while one is already active supersedes the prior record: its `status` flips to `SUPERSEDED` and its `version` bumps, while the new row is born `ACTIVE`. The create call is OCC-guarded on the contributor: the request must carry `expected_contributor_version` matching the contributor's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The window itself is validated — `effective_to` must be null or strictly later than `effective_from`, and the new agreement's `effective_from` must be at or after the prior active agreement's `effective_from`; a violation yields `ERR_INVALID_WINDOW`. Field-shape violations — both rate fields set, neither set, a rate below 1 — yield `ERR_INVALID_REQUEST`.

A `DeskAdmin` may revoke an `ACTIVE` agreement, moving it to `REVOKED`, but only when no in-flight assignment references it — that is, no assignment whose `editorial_status` is `OFFERED`, `ACCEPTED`, `IN_PROGRESS`, `SUBMITTED`, or `UNDER_VERIFICATION` pins this agreement. Revocation bumps the agreement's `version`.

### 3.3. Commissioning, Offering, and Accepting Assignments

An `Editor` drafts an assignment with the commissioned `contributor_id`, a working `title`, the `brief` body, a `commissioned_word_count` of at least 100 words, and a `deadline_utc` filing deadline. The new record starts in `DRAFT` editorial status with `payment_status` `UNINVOICED`. Its `final_word_count` is null until acceptance, `kill_fee_tier` is null until a kill, `agreed_fee_cents` is zero until offer, `final_fee_cents` is null until a terminal editorial state, `verification_cleared` is false, and `late_flag` is false.

Offering the assignment — an `Editor` action — is the moment the commercial terms crystallize. The precondition is threefold, evaluated in order: the assignment must be in `DRAFT`, the contributor must be `ACTIVE`, and an `ACTIVE` rate agreement must cover the current time (its `effective_from` at or before now and its `effective_to` either null or strictly after now); the last of these, when unmet, is rejected with `ERR_NO_ACTIVE_RATE_AGREEMENT`. On success the agreement is version-pinned into `rate_agreement_id`, `agreed_fee_cents` is locked from that agreement (for `PER_WORD`, the commissioned word count multiplied by `per_word_rate_cents`; for `FLAT`, the `flat_fee_cents`), and a `RightsPurchase` row is created alongside the assignment with `rights_kind` copied from the agreement's `rights_default` and `status` `ACTIVE`. The assignment's `version` bumps.

From `OFFERED`, the contributor themselves accepts (moving to `ACCEPTED`) — ownership is enforced by comparing `X-User-ID` to the assignment's `contributor_id`, with a mismatch rejected as `ERR_NOT_OWNER`. The same ownership rule guards starting work (`ACCEPTED` to `IN_PROGRESS`) and submitting the story. Submission moves the assignment to `SUBMITTED`, sets `late_flag` to true exactly when the submission time is later than `deadline_utc`, and then immediately auto-advances to `UNDER_VERIFICATION`.

### 3.4. Kill Fees, Acceptance, and the Dual-Variant Fee Calculation

The `assignment_fee_due` calculation has two variants pinned by evaluation order: base first, tier factor second, lateness third, integer result throughout.

The **accepted variant** fires when the assignment reaches `ACCEPTED_FOR_PUBLICATION`. The base is the agreed fee for `FLAT` agreements, but for `PER_WORD` agreements it is the editor-verified `final_word_count` multiplied by the pinned agreement's `per_word_rate_cents` — diverging from the commissioned basis locked in `agreed_fee_cents` whenever the final count differs from the commissioned count. The fee owed is this base, unmodified.

The **kill variant** fires when the assignment reaches `KILLED`. The tier percentage is 25 when `kill_fee_tier` is `PRE_DELIVERY`, or the desk's `kill_fee_post_delivery_pct_num` (default 50) when `POST_DELIVERY`. The fee is the agreed fee multiplied by the tier percentage and divided by 100, using floor division. When `late_flag` is true and the tier is `POST_DELIVERY`, the result is halved again — floor-divided by 2 — as the late-delivery kill penalty. The agreement's own `kill_fee_pct_num` is not consulted by this calculation; the desk-level tier in `DeskConfig` overrides it for the post-delivery branch.

An `Editor` may kill an assignment from `OFFERED`, `ACCEPTED`, or `IN_PROGRESS`: the kill is a pre-delivery kill, so `kill_fee_tier` becomes `PRE_DELIVERY` and `final_fee_cents` is the kill-variant result. Killing from `UNDER_VERIFICATION` is a post-delivery kill: `kill_fee_tier` becomes `POST_DELIVERY`, `final_fee_cents` follows the kill variant with the halving rule when the submission was late, and `verification_cleared` remains false unless every report is already `CLEARED` or `DISMISSED`. In both branches `payment_status` stays `UNINVOICED`, so a killed assignment can still be invoiced for its kill fee.

Acceptance for publication — an `Editor` action from `UNDER_VERIFICATION` — requires every verification report for the assignment to be `CLEARED` or `DISMISSED`, and the request body must carry `final_word_count`. On success the final count is recorded, `final_fee_cents` is computed by the accepted variant, `verification_cleared` flips to true (opening the invoicing gate on the payment dimension), and — when the assignment's rights purchase has `rights_kind` `ALL` — the `buyout_uplift_cents` on that record is computed by the rights-uplift rule (§3.6).

### 3.5. Verification Reports and the Plagiarism/AI Gate

The submission auto-transition creates two `VerificationReport` rows in pinned order: index 0 has `checker_kind` `PLAGIARISM`, index 1 has `checker_kind` `AI_CONTENT`, both `PENDING`. The list endpoint for verification reports returns them in creation order (`created_at` ascending), so the plagiarism report always appears first.

A `VerificationEditor` records results by submitting `similarity_score_bps` and `ai_probability_bps`, each between 0 and 10000. Results land only on a `PENDING` report: recording against a report in any other status is rejected with `ERR_INVALID_STATE`. The comparison that decides the outcome depends on the report kind. For a `PLAGIARISM` report, a `similarity_score_bps` strictly below the desk's `flag_threshold_bps` (default 2000, i.e. 20%) clears the report; a score at or above the threshold flags it. For an `AI_CONTENT` report, an `ai_probability_bps` strictly below the desk's `ai_flag_threshold_bps` (default 7000, i.e. 70%) clears it; at or above flags it. The boundary is inclusive on the flag side — exactly at threshold means `FLAGGED`. Clearing recomputes the assignment's `verification_cleared` (true exactly when every report of the assignment is `CLEARED` or `DISMISSED`); flagging closes the payment gate, blocking invoice submission while any report is `PENDING` or `FLAGGED` with `ERR_VERIFICATION_NOT_CLEARED`.

A `FLAGGED` report is adjudicated by a `VerificationEditor` who supplies an `outcome` and a non-empty `adjudication_note`. Segregation of duties applies: the adjudicator's `X-User-ID` must differ from the recorder's, else `ERR_SEGREGATION_OF_DUTIES`. An outcome of `DISMISSED` returns the report to a clean state and recomputes `verification_cleared`. An outcome of `CONFIRMED_VIOLATION` fires a depth-three cascade: the assignment auto-transitions from `UNDER_VERIFICATION` to `REJECTED_AFTER_FLAG`; its `final_fee_cents` is set to 0 (no fee and no kill fee on a confirmed violation); its `payment_status` cascades to `VOID`; every expense claim for the assignment in `PRE_APPROVAL_REQUESTED`, `APPROVED`, or `SUBMITTED` flips to `DENIED`; the rights purchase flips to `REVERTED`; and the contributor themselves flips to `SUSPENDED`.

### 3.6. Rights Purchases, Reuse Royalties, and the Buyout Uplift

Every assignment carries exactly one `RightsPurchase`, created at offer time. `rights_kind` of `FIRST` means first-publication rights only, already included in the fee. `ONE_TIME` means one-time non-exclusive rights; each subsequent reuse accrues a royalty. `ALL` means a full buyout, compensated by a one-time uplift.

The `reuse_payment` rule fires when an `Editor` records a reuse against an `ACTIVE` purchase. It is permitted only when `rights_kind` is `ONE_TIME` and the assignment is `ACCEPTED_FOR_PUBLICATION`; a reuse attempt against `FIRST` or `ALL` rights, a `REVERTED` purchase, or an assignment in any other editorial state is rejected with `ERR_RIGHTS_NOT_REUSABLE` (HTTP 409). The royalty is the assignment's `final_fee_cents` multiplied by the desk's `reuse_royalty_pct_num` (default 25) and divided by 100, floor-divided. Recording a reuse increments `reuse_count` by one, adds the royalty to `reuse_fee_cents_total`, and posts a `REUSE_ROYALTY_CREDIT` ledger entry immediately, which feeds the year-to-date gross aggregation.

The `rights_uplift` rule fires at acceptance-for-publication when the purchase's `rights_kind` is `ALL`: `buyout_uplift_cents` is the `final_fee_cents` multiplied by the desk's `all_rights_uplift_pct_num` (default 35) and divided by 100, floor-divided. The uplift is recorded on the rights purchase but enters the invoice fee basis by composition: when the assignment's rights are `ALL`, the invoice's `fee_claim_cents` must equal `final_fee_cents` plus `buyout_uplift_cents`, and invoice verification checks exactly that sum. For `FIRST` and `ONE_TIME` purchases the uplift stays at 0.

### 3.7. Expense Pre-Approval, Submission, and Settlement

Expense claims follow a two-stage pattern. A contributor first requests pre-approval on their own assignment — the claim's `assignment_id` ties it to that brief — supplying a `category` — one of `TRAVEL`, `MEALS`, `EQUIPMENT`, `OTHER` — and a `requested_cents` of at least 1; amounts below 1 are rejected with `ERR_INVALID_AMOUNT`. The claim starts at `PRE_APPROVAL_REQUESTED`.

An `Editor` then decides with a `decision` of `APPROVE` or `REJECT`. Approval requires the claim to be `PRE_APPROVAL_REQUESTED` and the assignment to be in `OFFERED`, `ACCEPTED`, or `IN_PROGRESS`; it sets `approved_cents` to the smaller of `requested_cents` and the category cap from the desk's `category_caps_cents` (defaults: `TRAVEL` 50000, `MEALS` 7500, `EQUIPMENT` 20000, `OTHER` 5000). Rejection moves the claim to `REJECTED` with no amount recorded.

Once `APPROVED`, the contributor submits the actual expense with `claimed_cents` (at least 1) and a `receipt_attached` flag. The receipt gate is a validation, not part of the reimbursement formula: when `claimed_cents` is at or above the desk's `receipt_required_cents` (default 2500), `receipt_attached` must be true, and its absence is rejected with `ERR_RECEIPT_REQUIRED`. Ownership is enforced against the claim's assignment's `contributor_id`.

Settlement is an `Editor` decision on a `SUBMITTED` claim. Reimbursement requires the assignment to be in `UNDER_VERIFICATION`, `ACCEPTED_FOR_PUBLICATION`, or `KILLED`; the `expense_reimbursement` rule sets `reimbursable_cents` to the smaller of `claimed_cents` and `approved_cents`. When the claim exceeds the approval the excess is silently forfeited — no error, no partial flag. Denial moves the claim to `DENIED` with `reimbursable_cents` set to 0. The claim reaches `PAID` only when an invoice covering it is settled by batch release, at which point the system posts the expense credit and flips the claim.

### 3.8. Tax Documents, Withholding, and Invoice Verification

A contributor submits a tax document against their own contributor id, choosing a `doc_kind` of `W9` or `W8BEN`, supplying `tin_last4` (exactly four digits), and — for `W8BEN` only — a `treaty_country` ISO code. The kind must match the contributor's `tax_residency`: `W9` pairs with `DOMESTIC_US`, `W8BEN` with `FOREIGN`; a mismatch, or a `W8BEN` without a `treaty_country`, is rejected with `ERR_TAX_DOC_MISMATCH`. The document is stamped with `submitted_at` from the logical clock, and `expires_at` is computed as `submitted_at` plus the desk's document validity of 1095 days (the W8BEN calendar rule is simplified to the same fixed window). New documents start at `SUBMITTED`.

A `FinanceUser` verifies or rejects via a `decision`; verification additionally requires the kind-to-residency match, so the rejection path exists for malformed submissions. A `REJECTED` document is immutable history — the contributor resubmits by creating a fresh document, which starts its own `SUBMITTED` lifecycle. Once `VERIFIED`, a document remains valid until the clock sweep finds `expires_at` in the past and flips it to `EXPIRED`, pushing subsequent withholding to the punitive branch.

Invoice submission by the contributor opens the payment dimension. The request carries `fee_claim_cents` and `expense_claim_cents`, both non-negative. The assignment must be in `ACCEPTED_FOR_PUBLICATION` or `KILLED`, and the verification gate must be open: either `verification_cleared` is true, or the assignment is `KILLED` with no report in `PENDING` or `FLAGGED`; otherwise the submission is rejected with `ERR_VERIFICATION_NOT_CLEARED`. The submission sets `submitted_by_contributor_id` from `X-User-ID` and moves `payment_status` from `UNINVOICED` to `INVOICED`. The new invoice starts at `SUBMITTED`, with `payment_terms_days` copied from the desk's `net_terms_days` (default 30) and `late_fee_cents` at 0.

Verification by a `FinanceUser` enforces its checks in a pinned order. The claim-reconciliation rule compares `fee_claim_cents` to the assignment's `final_fee_cents` — plus `buyout_uplift_cents` when rights are `ALL` — and `expense_claim_cents` to the sum of `reimbursable_cents` across the assignment's `REIMBURSABLE` expense claims; any disagreement is rejected with `ERR_CLAIM_MISMATCH`. On success, three computed fields land. `gross_cents` is the integer sum of `fee_claim_cents` and `expense_claim_cents`, no rounding. `withholding_cents` comes from the `withholding_computation` rule, which applies to the fee portion only — expenses are never withheld. `net_payable_cents` is `gross_cents` minus `withholding_cents`, per the `net_payable_allocation` rule. The evaluation order is pinned to resolve the circular-looking dependency: gross is computed first from fee plus expenses, withholding second from the fee alone (never from gross — that is the classic bug this pins against), net third as gross minus withholding. `due_date_utc` is set to now plus `payment_terms_days`. A `decision` of `REJECT` instead moves the invoice to `REJECTED` and compensates the payment dimension back from `INVOICED` to `UNINVOICED`, so the contributor may submit a fresh invoice.

The `withholding_computation` rule selects its branch in pinned order: domestic-backup first, domestic-normal second, foreign-treaty third, foreign-statutory fourth. The latest document is the contributor's most recently submitted `TaxDocument` whose `status` is `VERIFIED` and whose `expires_at` is at or after now; ties on `submitted_at` break toward the latest `created_at`. For a `DOMESTIC_US` contributor, if `backup_withholding_flag` is true or no such valid document exists, the rate is the desk's `backup_withholding_rate_bps` (default 2400, i.e. 24%); otherwise the rate is zero. For a `FOREIGN` contributor with no valid document, the rate is the desk's `foreign_statutory_rate_bps` (default 3000, i.e. 30%); with a valid `W8BEN`, the rate is looked up in the desk's `treaty_rates_bps` table keyed by `treaty_country` (defaults: `GB` 0, `DE` 0, `JP` 1000, `IN` 1500, `BR` 1500), and a country absent from the table falls back to the statutory rate. The withheld amount is the fee multiplied by the rate in basis points and divided by 10000, floor-divided.

Approval — a second `FinanceUser` distinct from the verifier, enforced as `ERR_SEGREGATION_OF_DUTIES` — requires the contributor to hold at least one `VERIFIED`, unexpired tax document at approval time; its absence is rejected with `ERR_TAX_DOC_MISSING`. Approval moves the invoice to `APPROVED` and cascades the assignment's `payment_status` from `INVOICED` to `PAYABLE`.

### 3.9. Payment Batches, Late Fees, and the Ledger

A `FinanceUser` opens a payment batch with a `scheduled_pay_date`; the batch starts `OPEN` with all three totals (`total_gross_cents`, `total_withholding_cents`, `total_net_cents`) at 0 and `locked_by_user_id` null. Adding an invoice requires the caller to supply the `invoice_id` of an `APPROVED` invoice and requires the batch to be `OPEN` — otherwise `ERR_BATCH_NOT_OPEN` — and sets the invoice's `payment_batch_id`, moves the invoice to `BATCHED`, recomputes the batch totals, and bumps the batch `version`.

Locking the batch moves it to `LOCKED`, records `locked_by_user_id` from the caller's `X-User-ID`, freezes the three totals, and bumps the version; locking an empty batch is rejected with `ERR_BATCH_NOT_OPEN`. Cancellation is allowed only from `OPEN`, moves the batch to `CANCELLED`, and compensates every member invoice back from `BATCHED` to `APPROVED` with `payment_batch_id` cleared to null. Release, by contrast, is the settlement event that lands the batch in `RELEASED`.

Release is the settlement event. It requires the batch `LOCKED`, a releasing `FinanceUser` whose `X-User-ID` differs from `locked_by_user_id` (segregation of duties), and `expected_batch_version` matching the batch's current `version` — a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). On release, the `late_fee` rule is evaluated per member invoice as of the batch's `scheduled_pay_date`: the days overdue is the integer number of days between the invoice's `due_date_utc` and the scheduled pay date, clamped at zero (a release exactly at the due date accrues nothing); the fee is the invoice's `net_payable_cents` multiplied by the desk's `late_fee_daily_bps` (default 50, i.e. 0.5% per day), multiplied by the days overdue, divided by 10000, floor-divided. The accrual is a daily step function, not continuous.

Each member invoice then posts its ledger entries and moves to `PAID`: a `FEE_CREDIT` entry of plus `fee_claim_cents`, an `EXPENSE_CREDIT` entry of plus `expense_claim_cents`, a `WITHHOLDING_DEBIT` entry of minus `withholding_cents`, and a `LATE_FEE_CREDIT` entry of plus `late_fee_cents` when that amount is positive. Every covered expense claim flips to `PAID`, and the assignment's `payment_status` cascades to `PAID`. The `contributor_ytd_gross` aggregation then recomputes per contributor: `ytd_gross_cents` is the sum of `amount_cents` over all the contributor's ledger entries whose `entry_kind` is `FEE_CREDIT`, `EXPENSE_CREDIT`, `LATE_FEE_CREDIT`, or `REUSE_ROYALTY_CREDIT` — `WITHHOLDING_DEBIT` entries never count toward gross — and whose `posted_at` falls within the current calendar year in UTC, inclusive of both January 1 00:00:00.000Z and December 31 23:59:59.999Z. `reportable_threshold_crossed` is then set to whether `ytd_gross_cents` is at least `reporting_threshold_cents`, boundary inclusive.

### 3.10. Desk Configuration Bootstrap

The desk's policy constants live on a singleton `DeskConfig` initialized once by a `DeskAdmin`; a second initialization attempt is rejected with `ERR_INVALID_STATE`. Every field is optional at bootstrap and falls back to its documented default: `kill_fee_post_delivery_pct_num` (50, between 1 and 100), `receipt_required_cents` (2500), `category_caps_cents` (the per-category object), `net_terms_days` (30), `late_fee_daily_bps` (50), `reporting_threshold_cents` (60000), `backup_withholding_rate_bps` (2400), `foreign_statutory_rate_bps` (3000), `treaty_rates_bps` (the five-country table), `flag_threshold_bps` (2000), `ai_flag_threshold_bps` (7000), `reuse_royalty_pct_num` (25), and `all_rights_uplift_pct_num` (35). All roles may read the configuration.

### 3.11. Validation Ordering Across the Surface

When several validations could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic. Authentication comes first (missing or malformed headers yield `ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then path existence left-to-right (`ERR_NOT_FOUND`), then state-machine legality including terminal-state lockdown (`ERR_INVALID_STATE`). Ownership (`ERR_NOT_OWNER`) is next — it guards the contributor's own accept, start, submit, invoice creation, expense-claim creation, expense submission, and tax-document submission. Business-safety gates follow: the verification gate (`ERR_VERIFICATION_NOT_CLEARED`) on invoice submission and invoice verification, then the three segregation-of-duties pairs (`ERR_SEGREGATION_OF_DUTIES`) on invoice approval, batch release, and report adjudication. Referential rules come after: rate-agreement resolvability (`ERR_NO_ACTIVE_RATE_AGREEMENT`) on offer, tax-document kind matching (`ERR_TAX_DOC_MISMATCH`) on document submission. Fiscal rules follow: tax-document presence (`ERR_TAX_DOC_MISSING`) on invoice approval, claim reconciliation (`ERR_CLAIM_MISMATCH`) on invoice verification. Then the constraint family: the receipt gate (`ERR_RECEIPT_REQUIRED`) on expense submission, amount sanity (`ERR_INVALID_AMOUNT`) on expense creation and submission, email uniqueness (`ERR_DUPLICATE_EMAIL`) on contributor creation, generic field-shape (`ERR_INVALID_REQUEST`) across the surface, the rate-agreement window (`ERR_INVALID_WINDOW`) on agreement creation, rights reusability (`ERR_RIGHTS_NOT_REUSABLE`) on record-reuse, batch openness (`ERR_BATCH_NOT_OPEN`) on add-invoice and lock. Stale-version rejection (`ERR_STALE_VERSION`) is the final check, evaluated only after every other rule has passed.

## 4. Endpoint Definitions

All endpoints live under the `/freelance-desk` prefix. Operations that create a new resource respond with HTTP 201; operations that modify an existing resource respond with HTTP 200. Reads respond with HTTP 200. Every request must carry `X-User-ID` and `X-User-Role` per §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /freelance-desk/_clock/set_current_utc | Advance the logical clock; sweeps expired tax documents | DeskAdmin |
| POST | /freelance-desk/desk-config | One-time bootstrap of desk policy constants | DeskAdmin |
| GET | /freelance-desk/desk-config | Read the desk configuration | DeskAdmin, Editor, FinanceUser, VerificationEditor, Contributor |
| POST | /freelance-desk/contributors | Add a contributor to the roster | DeskAdmin |
| GET | /freelance-desk/contributors | List contributors (filters: `status`, `tax_residency`, `reportable_threshold_crossed`) | DeskAdmin, Editor, FinanceUser |
| GET | /freelance-desk/contributors/{id} | Get one contributor; contributors read only their own row | DeskAdmin, Editor, FinanceUser, Contributor |
| POST | /freelance-desk/contributors/{id}/suspend | Suspend an active contributor | DeskAdmin |
| POST | /freelance-desk/contributors/{id}/reinstate | Reinstate a suspended contributor | DeskAdmin |
| POST | /freelance-desk/contributors/{id}/terminate | Terminate; supersedes agreements, kills draft/offered assignments | DeskAdmin |
| POST | /freelance-desk/contributors/{id}/rate-agreements | Create a rate agreement; supersedes prior active one; OCC-guarded | DeskAdmin |
| GET | /freelance-desk/contributors/{id}/rate-agreements | List a contributor's rate agreements | DeskAdmin, Editor, FinanceUser, Contributor |
| GET | /freelance-desk/rate-agreements/{id} | Get one rate agreement | DeskAdmin, Editor, FinanceUser, Contributor |
| POST | /freelance-desk/rate-agreements/{id}/revoke | Revoke an active agreement not referenced by in-flight assignments | DeskAdmin |
| POST | /freelance-desk/assignments | Create an assignment brief in DRAFT | Editor |
| GET | /freelance-desk/assignments | List assignments (filters: `contributor_id`, `rate_agreement_id`, `editorial_status`, `payment_status`) | DeskAdmin, Editor, FinanceUser, VerificationEditor, Contributor |
| GET | /freelance-desk/assignments/{id} | Get one assignment | DeskAdmin, Editor, FinanceUser, VerificationEditor, Contributor |
| POST | /freelance-desk/assignments/{id}/offer | Offer; pins rate agreement, creates rights purchase | Editor |
| POST | /freelance-desk/assignments/{id}/accept | Contributor accepts the offered assignment | Contributor |
| POST | /freelance-desk/assignments/{id}/start | Contributor marks work started | Contributor |
| POST | /freelance-desk/assignments/{id}/submit | Contributor submits; sets late flag, auto-creates verification reports | Contributor |
| POST | /freelance-desk/assignments/{id}/kill | Editor kills the assignment; kill fee per tier and lateness | Editor |
| POST | /freelance-desk/assignments/{id}/accept-for-publication | Editor accepts after verification; records final word count | Editor |
| GET | /freelance-desk/assignments/{id}/verification-reports | List an assignment's verification reports (filters: `status`, `checker_kind`) | DeskAdmin, Editor, VerificationEditor, FinanceUser |
| GET | /freelance-desk/verification-reports/{id} | Get one verification report | DeskAdmin, Editor, VerificationEditor, FinanceUser |
| POST | /freelance-desk/verification-reports/{id}/record-result | Record checker scores; below threshold clears, at/above flags | VerificationEditor |
| POST | /freelance-desk/verification-reports/{id}/adjudicate | Adjudicate a flagged report; segregation of duties vs recorder | VerificationEditor |
| POST | /freelance-desk/assignments/{id}/expense-claims | Request expense pre-approval for an assignment | Contributor |
| GET | /freelance-desk/assignments/{id}/expense-claims | List an assignment's expense claims (filter: `status`) | DeskAdmin, Editor, FinanceUser, Contributor |
| GET | /freelance-desk/expense-claims/{id} | Get one expense claim | DeskAdmin, Editor, FinanceUser, Contributor |
| POST | /freelance-desk/expense-claims/{id}/decide | Editor decides pre-approval; approved amount capped at category cap | Editor |
| POST | /freelance-desk/expense-claims/{id}/submit | Contributor submits actual expense with receipt flag | Contributor |
| POST | /freelance-desk/expense-claims/{id}/settle-decision | Editor settles the claim; reimbursable is min(claimed, approved) | Editor |
| GET | /freelance-desk/assignments/{id}/rights-purchases | List an assignment's rights purchases (filter: `status`) | DeskAdmin, Editor, FinanceUser, Contributor |
| GET | /freelance-desk/rights-purchases/{id} | Get one rights purchase | DeskAdmin, Editor, FinanceUser, Contributor |
| POST | /freelance-desk/rights-purchases/{id}/record-reuse | Record a reuse of ONE_TIME rights; accrues royalty | Editor |
| POST | /freelance-desk/contributors/{id}/tax-documents | Submit a tax document (W9 or W8BEN) | Contributor |
| GET | /freelance-desk/contributors/{id}/tax-documents | List a contributor's tax documents (filters: `status`, `doc_kind`) | DeskAdmin, FinanceUser, Contributor |
| GET | /freelance-desk/tax-documents/{id} | Get one tax document | DeskAdmin, FinanceUser, Contributor |
| POST | /freelance-desk/tax-documents/{id}/verify | Finance verifies or rejects a submitted document | FinanceUser |
| POST | /freelance-desk/assignments/{id}/invoices | Contributor submits an invoice for the assignment | Contributor |
| GET | /freelance-desk/assignments/{id}/invoices | List invoices of an assignment (filter: `status`) | DeskAdmin, Editor, FinanceUser, Contributor |
| GET | /freelance-desk/invoices | List invoices (filters: `status`, `payment_batch_id`, `submitted_by_contributor_id`) | DeskAdmin, FinanceUser |
| GET | /freelance-desk/invoices/{id} | Get one invoice | DeskAdmin, FinanceUser, Contributor |
| POST | /freelance-desk/invoices/{id}/verify | Finance verifies claim amounts; computes gross/withholding/net; or rejects | FinanceUser |
| POST | /freelance-desk/invoices/{id}/approve | Second finance user approves; requires valid tax document | FinanceUser |
| POST | /freelance-desk/payment-batches | Create an open payment batch | FinanceUser |
| GET | /freelance-desk/payment-batches | List payment batches (filter: `status`) | DeskAdmin, FinanceUser |
| GET | /freelance-desk/payment-batches/{id} | Get one payment batch | DeskAdmin, FinanceUser |
| POST | /freelance-desk/payment-batches/{id}/add-invoice | Add an APPROVED invoice to an OPEN batch | FinanceUser |
| POST | /freelance-desk/payment-batches/{id}/lock | Lock the batch; freezes totals; records locker | FinanceUser |
| POST | /freelance-desk/payment-batches/{id}/release | Release a locked batch by a different finance user; posts ledger entries; OCC-guarded | FinanceUser |
| POST | /freelance-desk/payment-batches/{id}/cancel | Cancel an open batch; member invoices return to APPROVED | FinanceUser |
| GET | /freelance-desk/contributors/{id}/ledger-entries | List a contributor's ledger entries (filter: `entry_kind`) | DeskAdmin, FinanceUser, Contributor |
| GET | /freelance-desk/invoices/{id}/ledger-entries | List ledger entries posted for an invoice | DeskAdmin, FinanceUser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_NOT_OWNER | 403 |
| ERR_VERIFICATION_NOT_CLEARED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NO_ACTIVE_RATE_AGREEMENT | 422 |
| ERR_TAX_DOC_MISMATCH | 422 |
| ERR_TAX_DOC_MISSING | 422 |
| ERR_CLAIM_MISMATCH | 422 |
| ERR_RECEIPT_REQUIRED | 422 |
| ERR_INVALID_AMOUNT | 422 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_WINDOW | 422 |
| ERR_RIGHTS_NOT_REUSABLE | 409 |
| ERR_BATCH_NOT_OPEN | 409 |
| ERR_STALE_VERSION | 412 |
