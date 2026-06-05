# HSA / FSA Health Accounts API — Product Requirements Document

## 1. Introduction

Employer-sponsored tax-advantaged health accounts — Health Savings Accounts (HSA), Health Flexible Spending Arrangements (Health FSA), and Dependent Care FSAs (DCFSA) — sit at the intersection of two unforgiving disciplines: penny-exact ledger reconciliation and IRS-grade compliance auditing. This API administers the full lifecycle of those accounts on behalf of a plan administrator: it provisions plan years with their statutory contribution and election caps, opens and funds accounts, accepts and adjudicates reimbursement claims for qualified expenses, disburses approved claims through treasury batches, and runs the year-end settlement that decides — under use-it-or-lose-it, a grace period, or a capped carryover — exactly how many unused cents are forfeited versus rolled forward.

The hardest requirements in this domain are not the happy paths but the reconciliation invariants that surround them. Every dollar that moves leaves an immutable ledger entry so the IRS audit trail is reconstructable; derived balances are recomputed synchronously inside the request that triggers them; the person who approves a claim may never be the person who pays it; and a forward-looking approval that over-projected an HSA's not-yet-deposited payroll must be caught again, against real cash on hand, at the moment funds actually leave the account. This document specifies the entities, state machines, calculations, validations, and access-control rules that together enforce those invariants.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. The business workflows in Section 3 assume everything here.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `PlanAdmin`, `Participant`, `Adjudicator`, and `FundDisburser`.

A `PlanAdmin` is the plan administrator who provisions plan years, opens and activates accounts, posts and reverses contributions, runs year-end settlement, clears compliance holds, performs the clawback of an already-reimbursed claim, and drives the test clock. When `X-User-Role` is `PlanAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a transition writes an operator id (for example, as `adjudicated_by` is written by an `Adjudicator` or `reimbursed_by` by a `FundDisburser`), but it never compares a `PlanAdmin` id to any entity's `id`.

A `Participant` is the account owner who submits and resubmits claims for accounts they own. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` entity; ownership checks on any resource that references a `Participant` compare the resource's owning `participant_id` (for a claim, the `participant_id` of the claim's account) to `X-User-ID`. A `Participant` who acts on a claim or account they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

An `Adjudicator` decides claims — approving, denying, or requesting documentation — and may void an approved claim before any cash has moved. A `FundDisburser` is the treasury operator who builds and disburses reimbursement batches and may not pay a claim they themselves approved. When `X-User-Role` is `Adjudicator` or `FundDisburser`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity: the adjudicator's id is recorded on the claim as `adjudicated_by`, the disburser's id as `reimbursed_by`, and the segregation-of-duties check compares those two recorded operator ids rather than matching either against an entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0 (minimum 0). An out-of-range value is silently clamped into range rather than rejected — a `limit` below 1 is raised to 1 and one above 100 is lowered to 100, and a negative `offset` is raised to 0 — while a `limit` or `offset` that is not a valid integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless explicitly stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties, Versioning, and Auditability

Most primary resources — `Participant`, `PlanYear`, `Account`, `Contribution`, `Claim`, and `ReimbursementBatch` — carry a standard system-managed set of fields. Each has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when the resource was first created, an `updated_at` timestamp following the same format and refreshed on every mutation, and a `version` integer that starts at 1 and increments by one on every mutation to the resource.

Two entities are deliberate exceptions because they are immutable once written. A `LedgerEntry` carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because the audit trail is append-only and a posted entry is never edited. The `ClockState` likewise is a singleton control record and carries no `updated_at` or `version`. Wherever a derived field on an `Account` (such as `available_balance_cents`) is recomputed, that recomputation is itself a mutation of the `Account`: it refreshes `updated_at` and increments `version`.

### 2.5. The Append-Only IRS Audit Trail

Every movement of money is recorded as an immutable `LedgerEntry` so the account history is reconstructable for IRS audit. Each entry names the `account_id` it belongs to and, when the event originated from a claim, the `claim_id` that produced it (entries of type `CONTRIBUTION`, `CONTRIBUTION_REVERSAL`, `FORFEITURE`, `CARRYOVER_OUT`, and `CARRYOVER_IN` carry no `claim_id`). Its `entry_type` is one of `CONTRIBUTION`, `CONTRIBUTION_REVERSAL`, `REIMBURSEMENT`, `REIMBURSEMENT_REVERSAL`, `FORFEITURE`, `CARRYOVER_OUT`, or `CARRYOVER_IN`. The `amount_cents` on a ledger entry is always a positive integer recording the magnitude of the event; direction (debit versus credit) is conveyed by `entry_type`, never by sign. A human-readable `memo` accompanies each entry, for example noting that a claim was reimbursed under the chronological algorithm. Ledger entries are never updated or deleted; a correction is itself a new compensating entry.

### 2.6. Monetary Precision

Every monetary quantity in this system is an integer count of cents. There are no fractional cents and therefore no rounding step: contribution amounts, election amounts, caps, balances, forfeitures, and carryovers are all whole-cent integers, and all arithmetic over them is exact integer arithmetic.

### 2.7. The Two Independent Account Dimensions

An `Account` evolves along two independent state dimensions that live side by side on the same row. The first is `funding_status`, which moves through `PENDING` (created but not yet funded), `ACTIVE` (open for claims and reimbursement), `DEPLETED` (its `available_balance_cents` has reached 0), and `CLOSED` (terminal, reached only at year-end settlement). The second is `compliance_hold`, which is either `CLEAR` (no hold) or `HELD` (an unsubstantiated reimbursed claim is blocking further reimbursements until the documentation is supplied). These two dimensions advance separately: an account can be `ACTIVE` and `HELD` at the same time, and clearing a hold does not change `funding_status`. Whenever either dimension changes the row is mutated, so `updated_at` is refreshed and `version` is incremented.

### 2.8. Nested-Resource Path Validation

Several endpoints address sub-resources of an account — for example its contributions or its ledger entries — or address a specific contribution under an account. For any path that carries more than one identifier, the server validates each path segment from left to right and rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. Reversing a contribution, for instance, first confirms the account exists before it confirms the contribution under it. Body-referenced foreign keys — `account_id`, `plan_year_id`, `participant_id`, and every member of `claim_ids` — are likewise required to reference existing entities, and a dangling reference is rejected with the same `ERR_RESOURCE_NOT_FOUND`.

### 2.9. Optimistic Concurrency on Account Writes

Three write operations against an `Account` are guarded by optimistic concurrency control, because each one reads a derived balance, makes a decision against it, and writes the result; a stale read would let the decision be made against a superseded snapshot. Posting a contribution, reversing a contribution, and disbursing a reimbursement batch each require an `expected_account_version` field in the request body carrying the client's last-observed `version` of the account being written.

When a contribution is posted, the request to that account's contribution-posting operation must carry `expected_account_version` equal to the account's current `version`. A prior contribution, or a cascaded balance recompute from a reimbursement, legitimately advances the account's `version`; if the poster's `expected_account_version` does not equal the live `version`, the post is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), so the contribution cap is always evaluated against the current `contributed_cents` rather than a stale one. The same guard applies when reversing a posted contribution: that operation also carries `expected_account_version`, and a mismatch yields `ERR_STALE_ACCOUNT_VERSION` (HTTP 412).

Disbursing a reimbursement batch carries `expected_account_version` for the account being drawn down. If another disbursement, contribution, or clawback has advanced that account's `version` since the disburser last read it, the carried `expected_account_version` is stale and the disbursement is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), forcing the disburser to re-read `available_balance_cents` before drawing the account down again. A batch may draw on several accounts, but the request carries a single `expected_account_version`; that value is compared against each distinct account's `version` only the first time that account is touched during the disburse, and the per-reimbursement version bumps the disburse itself applies do not re-trigger the OCC check on later claims drawing the same account. Operations not in this set do not take a version field, with the sole additional exception of the participant-update operation, which carries `expected_participant_version` against the `Participant` row it edits; when that field does not equal the participant's live `version`, the update is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412).

### 2.10. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of path resources validated left to right (`ERR_RESOURCE_NOT_FOUND`), then existence of body foreign keys (`ERR_RESOURCE_NOT_FOUND`), then participant resource-ownership (`ERR_NOT_RESOURCE_OWNER`), then whether the target resource is in a state that permits the transition (`ERR_INVALID_STATE`). Only after those structural gates do the domain-specific checks run — segregation of duties, compliance hold, expense qualification, service window, duplicate detection, cap checks, coverage-window overlap, funds availability, optimistic-concurrency version match, relief-mode coherence, body well-formedness, filing-window timeliness, and email uniqueness — each described with its triggering condition in Section 3 alongside the workflow it guards. Where two checks in that domain group could both apply on the same endpoint, their relative ordering is called out in the workflow narrative.

Body well-formedness is enforced on every create and update operation: a request missing a required field, carrying an invalid enum value, supplying a non-positive amount where a positive integer is required, or supplying an OCC version field of the wrong type is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Participants and Plan Years: Provisioning the Statutory Frame

A `PlanAdmin` registers a `Participant` by supplying an `email`, a `full_name`, and a `birth_date` (an ISO 8601 calendar date in the past — strictly before the current server-clock date; a `birth_date` on or after that date is rejected with `ERR_INVALID_REQUEST`). The `email` must be unique across all participants; a collision is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). Two further attributes may be supplied at registration and updated later: `marital_status`, which is one of `SINGLE`, `MARRIED_JOINT`, or `MARRIED_SEPARATE` and defaults to `SINGLE`, and `hdhp_covered`, a flag that is `true` when the participant is enrolled in a High-Deductible Health Plan and defaults to `false`. The `marital_status` later selects the Dependent Care FSA cap, and `hdhp_covered` gates HSA activation. A `PlanAdmin` may amend a participant's `marital_status` and `hdhp_covered` through the participant-update operation, which carries `expected_participant_version` matching the participant's current `version` and increments that `version` by one on success.

A plan year is the container that fixes every statutory limit for a coverage period. Creating one requires a non-empty `label` (for example a year tag; the label need not be unique across plan years, and no collision check is run on it), a `coverage_start` and `coverage_end` (ISO 8601 dates bounding the in-year service window inclusively — a `service_date` falling on or between them is in-year), and a `run_out_end`, the inclusive date through which in-year claims may still be filed. The `run_out_end` must be on or after `coverage_end`. The plan year also carries the full schedule of caps in cents: `hsa_individual_cap_cents` (the HSA limit for self-only HDHP coverage, greater than zero), `hsa_family_cap_cents` (the HSA limit for family coverage, strictly greater than the individual cap), `hsa_catchup_cents` (the additional HSA amount permitted for participants who are at least 55, at least zero), `health_fsa_cap_cents` (the Health FSA election limit, greater than zero), `dcfsa_cap_joint_cents` (the DCFSA limit for `SINGLE` or `MARRIED_JOINT` participants, greater than zero), and `dcfsa_cap_separate_cents` (the DCFSA limit for `MARRIED_SEPARATE` participants, greater than zero and strictly less than the joint cap, typically half of it).

Year-end relief for a Health FSA is governed by `fsa_relief_mode`, one of `NONE`, `GRACE_PERIOD`, or `CARRYOVER`, defaulting to `NONE`. These three are mutually exclusive: a single plan may never elect both a grace period and a carryover. Under `GRACE_PERIOD`, a `grace_period_end` date extends the in-year service window — a `service_date` on or before `grace_period_end` is still treated as in-year — and that date must be strictly after `coverage_end` and on or before `run_out_end`; it is null and ignored under the other two modes. Under `CARRYOVER`, `carryover_cap_cents` (at least zero) is the maximum Health FSA unused balance that rolls forward to the next plan year; it is ignored under the other two modes. At creation the server runs a relief-config coherence check: electing `GRACE_PERIOD` without a valid `grace_period_end`, electing `CARRYOVER` with a `carryover_cap_cents` of zero, or requesting both relief mechanisms at once is rejected with `ERR_RELIEF_MODE_CONFLICT` (HTTP 422). A plan year's `lifecycle` is a computed field that begins at `OPEN` and becomes `SETTLED` only after settlement has swept its accounts.

### 3.2. Opening and Activating an Account

A `PlanAdmin` opens an `Account` for a participant under a plan year, naming the owning `participant_id`, the electing `plan_year_id`, and the `account_type` — `HSA`, `HEALTH_FSA`, or `DCFSA` — which governs which cap, relief, funding basis, and forfeiture rules apply. For an HSA the `coverage_tier` (`SELF_ONLY` or `FAMILY`, defaulting to `SELF_ONLY`) selects which HSA cap applies; the tier is ignored for the two FSA types. The `elected_amount_cents` (at least zero) is the annual election: for a Health FSA or DCFSA it is the full-year pledge, and for an HSA it is the funding target that contributions accrue toward. An optional `auto_adjudication_threshold_cents` (at least zero, defaulting to zero) marks the amount at or below which a claim may be approved without itemized documentation.

When the account is for a Health FSA or DCFSA, the election is checked against the plan-year cap at open time. For a Health FSA the applicable cap is `health_fsa_cap_cents`. For a DCFSA the cap depends on the owning participant's `marital_status`: a `MARRIED_SEPARATE` participant is held to `dcfsa_cap_separate_cents`, while a `SINGLE` or `MARRIED_JOINT` participant is held to `dcfsa_cap_joint_cents`. Any prior-year carryover credited into the account does not consume the current-year election cap. An election equal to the applicable cap is accepted; only an `elected_amount_cents` strictly greater than the cap is rejected, with `ERR_ELECTION_CAP_EXCEEDED` (HTTP 422). HSA accounts are not election-capped at open time; their limit is enforced contribution by contribution.

Opening a Health FSA or DCFSA also runs a coverage-window-overlap guard against the participant's existing non-`CLOSED` accounts of the same `account_type`. For a Health FSA the effective coverage interval is the closed interval from `coverage_start` to an effective end, where the effective end is the later of `coverage_end` and, when the plan year elects `GRACE_PERIOD`, `grace_period_end` (otherwise just `coverage_end`); two Health FSA windows collide when the new account's start is on or before the existing account's effective end and the existing account's start is on or before the new account's effective end — so a single shared boundary day is a collision. For a DCFSA the interval is half-open, from `coverage_start` up to but not including `coverage_end`; two DCFSA windows collide when the new account's start is strictly before the existing account's `coverage_end` and the existing account's start is strictly before the new account's `coverage_end` — so a shared boundary day is not a collision, and back-to-back DCFSA years are permitted. HSA windows are never checked against one another. A detected overlap is rejected with `ERR_COVERAGE_WINDOW_OVERLAP` (HTTP 409).

A freshly opened account begins with `funding_status` of `PENDING` and `compliance_hold` of `CLEAR`. Activation, performed by a `PlanAdmin`, moves `funding_status` from `PENDING` to `ACTIVE` so the account will accept claims and reimbursements. Activation is permitted only while the account is `PENDING`; otherwise it is rejected with `ERR_INVALID_STATE` (HTTP 409). For a Health FSA or DCFSA, activation additionally requires `elected_amount_cents` to be greater than zero; for an HSA it requires the owning participant's `hdhp_covered` to be `true`. On activation the server runs the available-balance computation to seed the account's spendable balance and increments the account's `version` by one.

### 3.3. Contributions and the HSA Contribution Cap

A `PlanAdmin` posts a `Contribution` against an account by supplying `amount_cents` (always greater than zero), a `source` of `PAYROLL`, `EMPLOYER`, or `INDIVIDUAL`, a `posted_at` ISO 8601 datetime recording when the money is credited (used to order drawdown chronologically), and the OCC field `expected_account_version`. A contribution's `status` is computed and begins at `POSTED`; only a `POSTED` contribution counts toward the account's funded total, and a contribution moves to `REVERSED` exactly once if it is later corrected.

For HSA accounts the contribution must pass the contribution-cap check before it is accepted. The base cap is the family cap, `hsa_family_cap_cents`, when the account's `coverage_tier` is `FAMILY`, and otherwise the individual cap, `hsa_individual_cap_cents`. A catch-up allowance is added when the participant is old enough: the participant's age at the close of the plan year is the whole number of years between their `birth_date` and the plan year's `coverage_end`, taking the floor; if that age is at least 55, the catch-up amount `hsa_catchup_cents` is added to the base cap, and otherwise nothing is added. The total allowed is the base cap plus any catch-up. The prospective funded total is the account's current `contributed_cents` plus the incoming `amount_cents`. A prospective total equal to the allowed cap is accepted; only a prospective total strictly greater than the allowed cap is rejected, with `ERR_CONTRIBUTION_CAP_EXCEEDED` (HTTP 422). All three contribution sources — `PAYROLL`, `EMPLOYER`, and `INDIVIDUAL` — count toward this single shared cap, for both the self-only and family tiers.

A successful contribution post appends a `CONTRIBUTION` `LedgerEntry`, recomputes the account's `contributed_cents` and `available_balance_cents` via the available-balance rule, and increments the account's `version` by one. If the account had been `DEPLETED` and the new contribution lifts its `available_balance_cents` above zero, the account re-opens, moving `funding_status` from `DEPLETED` back to `ACTIVE`. Reversing a `POSTED` contribution — a `PlanAdmin` correction — moves that contribution's `status` from `POSTED` to `REVERSED`, appends a `CONTRIBUTION_REVERSAL` `LedgerEntry`, recomputes `contributed_cents` and `available_balance_cents`, and increments the account's `version` by one; if that recompute lifts a `DEPLETED` account's balance above zero it likewise transitions `DEPLETED` back to `ACTIVE`. A reversal is permitted only while the contribution is `POSTED`; an attempt to reverse an already-`REVERSED` contribution is an `ERR_INVALID_STATE` (HTTP 409).

The available balance itself is a synchronous aggregation. The account's `contributed_cents` is the sum of `amount_cents` over its `POSTED` contributions (reversed ones excluded). Its `reimbursed_cents` is the sum of `amount_cents` over its `REIMBURSEMENT` ledger entries minus the sum of `amount_cents` over its `REIMBURSEMENT_REVERSAL` ledger entries. From these, `available_balance_cents` is `contributed_cents` minus `reimbursed_cents` for an HSA, and `elected_amount_cents` plus `carried_in_cents` minus `reimbursed_cents` for a Health FSA or DCFSA.

### 3.4. Submitting and Adjudicating Claims

A `Participant` (or a `PlanAdmin` acting on their behalf) files a `Claim` against an account, supplying the `account_id`, the `service_date` (ISO 8601 date the service was incurred), the `expense_category` — one of `MEDICAL`, `DENTAL`, `VISION`, `PRESCRIPTION`, `DEPENDENT_CARE`, or `OTC` — the `claimed_amount_cents` requested (greater than zero), and optionally `substantiated`, a flag that is `true` when itemized documentation is attached and defaults to `false`. A claim's `status` is computed and starts at `SUBMITTED`; its `reimbursable_amount_cents` is computed later at adjudication and starts at zero. When a `Participant` files a claim, ownership is enforced: the claim's account must belong to that participant, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

Three guards run when a claim is filed. First, the expense must be qualified for the account type: `DEPENDENT_CARE` is permitted only on a DCFSA, while `MEDICAL`, `DENTAL`, `VISION`, `PRESCRIPTION`, and `OTC` are permitted only on an HSA or Health FSA; a `DEPENDENT_CARE` claim against an HSA or Health FSA, or any medical-category claim against a DCFSA, is rejected with `ERR_EXPENSE_NOT_QUALIFIED` (HTTP 422). Second, the `service_date` must fall within the account's effective service window — from `coverage_start` through `coverage_end`, extended through `grace_period_end` when the plan year elects `GRACE_PERIOD` — and a date outside that window is rejected with `ERR_SERVICE_DATE_OUTSIDE_WINDOW` (HTTP 422). Third, the filing must be timely: the current server date must be on or before the account's effective filing deadline, which is `run_out_end`, or `grace_period_end` when the plan year elects `GRACE_PERIOD` and that date is later; a filing after the deadline is rejected with `ERR_FILING_WINDOW_CLOSED` (HTTP 422). A duplicate guard also applies at filing: if another claim on the same account in any status other than `DENIED` or `VOIDED` already has the identical `service_date`, `expense_category`, and `claimed_amount_cents`, the new claim is rejected with `ERR_DUPLICATE_CLAIM` (HTTP 409).

An `Adjudicator` decides a claim that is in `SUBMITTED` (or, for denial, in `PENDING_SUBSTANTIATION`) by supplying a `decision` of `APPROVE`, `DENY`, or `REQUEST_DOCS`, and optionally a `denial_reason`. The decision records the adjudicator's `X-User-ID` as `adjudicated_by` and increments the claim's `version` by one. Approval moves the claim from `SUBMITTED` to `APPROVED`; it requires that the expense be qualified and the `service_date` be in-window (re-checked here, with the same `ERR_EXPENSE_NOT_QUALIFIED` and `ERR_SERVICE_DATE_OUTSIDE_WINDOW`), that the claim be either `substantiated` or have a `claimed_amount_cents` at or below the account's `auto_adjudication_threshold_cents` (an unsubstantiated claim above that threshold fails this gate with `ERR_INVALID_STATE` (HTTP 409)), and that the forward-looking reimbursable computation yield an amount greater than zero. If that projected amount would be zero, the approval is rejected for lack of funds with `ERR_INSUFFICIENT_FUNDS` (HTTP 422). Approval computes and stores `reimbursable_amount_cents` on the claim and leaves `denial_reason` null.

A `REQUEST_DOCS` decision is available only when the claim is `SUBMITTED`, is not `substantiated`, and has a `claimed_amount_cents` strictly greater than the account's `auto_adjudication_threshold_cents`; it moves the claim from `SUBMITTED` to `PENDING_SUBSTANTIATION` and records `adjudicated_by`. A `REQUEST_DOCS` against a claim that is already `substantiated`, or whose `claimed_amount_cents` is at or below that threshold, is rejected with `ERR_INVALID_STATE` (HTTP 409). A `DENY` decision moves a `SUBMITTED` claim to `DENIED`, setting `denial_reason` to the value supplied on the request, which must be one of `NOT_QUALIFIED`, `OUTSIDE_WINDOW`, `INSUFFICIENT_FUNDS`, or `DUPLICATE`; when no `denial_reason` is supplied on the request the server records `NOT_QUALIFIED` by default. A `DENY` of a `PENDING_SUBSTANTIATION` claim also moves it to `DENIED` but fixes `denial_reason` to `UNSUBSTANTIATED`, ignoring any supplied value. `DENIED` is terminal. Adjudicating a claim that is not in a state permitting the chosen transition is rejected with `ERR_INVALID_STATE`.

A claim in `PENDING_SUBSTANTIATION` returns to the queue when the `Participant` resubmits it with documentation: the resubmit operation requires `substantiated` to be supplied as `true`, sets the claim's `substantiated` to `true`, moves it from `PENDING_SUBSTANTIATION` back to `SUBMITTED` (the revision loop, re-entering adjudication), and increments `version` by one.

### 3.5. The Forward-Looking versus Chronological Reimbursable Amount

The reimbursable amount of a claim is computed twice, by two variants of the same rule, and the two variants can diverge for an HSA. At approval the forward-looking variant runs: it projects the account's funding basis so an approval need not wait for cash to physically land. The projected basis is `elected_amount_cents` minus `reimbursed_cents` for an HSA (the full annual target, projecting payroll that has not yet posted), `elected_amount_cents` plus `carried_in_cents` minus `reimbursed_cents` for a Health FSA (uniform coverage — the full election is available from day one), and `contributed_cents` minus `reimbursed_cents` for a DCFSA (pay-as-you-go — only funds actually contributed so far are available). The stored `reimbursable_amount_cents` is the smaller of the claim's `claimed_amount_cents` and the projected basis floored at zero (that is, the projected basis when positive, otherwise zero).

At disbursement the chronological, final variant re-evaluates the same claim against real cash on hand — the account's `available_balance_cents` (`contributed_cents` minus `reimbursed_cents` for an HSA; `elected_amount_cents` plus `carried_in_cents` minus `reimbursed_cents` for a Health FSA or DCFSA). If cash on hand is less than the claim's stored `reimbursable_amount_cents`, the disbursement of that claim is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 422): the forward-looking approval had over-projected an HSA whose payroll contributions had not yet landed. For a Health FSA or DCFSA the two variants agree, because the funding basis used at approval matches the cash basis at disbursement; they diverge only for an HSA whose `contributed_cents` is still below its `elected_amount_cents`.

### 3.6. Disbursement: Batches, Segregation of Duties, and Cascades

A `FundDisburser` (or a `PlanAdmin`) creates a `ReimbursementBatch` over a participant's approved claims by supplying the `participant_id` and an ordered `claim_ids` list. At creation the batch starts in `DRAFT`, and every claim named must be `APPROVED` and owned by that `participant_id`. The batch's `total_reimbursed_cents` is computed at disbursement and starts at zero. A batch can settle across several accounts of the one participant, since its claims may draw on different accounts.

A `FundDisburser` disburses the batch, supplying `expected_account_version` for the account being drawn down. The disburser processes the member claims strictly in `claim_ids` order, and for each one enforces four preconditions: the claim must still be `APPROVED`; its account's `compliance_hold` must be `CLEAR`; the segregation-of-duties rule must hold, meaning the disburser's `X-User-ID` must differ from the claim's recorded `adjudicated_by`; and the account must be `ACTIVE` with `available_balance_cents` at least the claim's `reimbursable_amount_cents` under the chronological variant. A segregation breach is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); a held account with `ERR_ACCOUNT_ON_HOLD` (HTTP 409); a cash shortfall with `ERR_INSUFFICIENT_FUNDS` (HTTP 422); a claim no longer `APPROVED`, or an account whose `funding_status` is anything other than `ACTIVE` at draw-down (for example a `DEPLETED` account), with `ERR_INVALID_STATE` (HTTP 409) — the not-`ACTIVE` check is evaluated before the cash-shortfall check. Among the per-claim domain checks, segregation of duties is evaluated before the compliance-hold check, which is evaluated before the funds check.

If the very first member claim fails any of its per-claim preconditions, the whole disbursement is rejected with that claim's error and the batch stays `DRAFT`. Otherwise, each claim that passes is reimbursed: the claim moves from `APPROVED` to `REIMBURSED`, a `REIMBURSEMENT` `LedgerEntry` for its `reimbursable_amount_cents` is appended, its `reimbursed_by` is set to the disburser's `X-User-ID`, and the account's `reimbursed_cents` and `available_balance_cents` are recomputed (a cascade that mutates the account). If a claim is reimbursed but its `available_balance_cents` reaches zero, the account's `funding_status` moves from `ACTIVE` to `DEPLETED`, and no further reimbursement on that account succeeds until a contribution or a reimbursement reversal restores a positive balance. If a reimbursed claim was not `substantiated`, the account's `compliance_hold` moves from `CLEAR` to `HELD`, blocking subsequent reimbursements on that account until the hold is cleared. Each account drawn down has its `version` incremented by one.

When every member claim reimburses successfully, the batch's `total_reimbursed_cents` is set to the sum of the reimbursed claims' `reimbursable_amount_cents` and the batch moves from `DRAFT` to `SETTLED`. When at least one claim reimburses but at least one later claim is skipped (because it failed one of its per-claim preconditions after an earlier claim already succeeded), the batch moves from `DRAFT` to `PARTIAL`, and `total_reimbursed_cents` reflects only the reimbursed subset. A `PARTIAL` outcome therefore arises only when some claims succeed and a later one is skipped — never from a first-claim failure, which rejects the whole disbursement.

### 3.7. Compliance Holds and Voiding Claims

A compliance hold exists to stop money flowing out of an account that has paid an unsubstantiated claim. Once an account is `HELD`, a `PlanAdmin` clears it through the clear-hold operation, but only when every `REIMBURSED` claim on that account now has `substantiated` equal to `true`; the operation moves `compliance_hold` from `HELD` to `CLEAR`, lets reimbursements resume, and increments the account's `version` by one. Clearing a hold that is already `CLEAR`, or while an unsubstantiated reimbursed claim remains, is an `ERR_INVALID_STATE`.

A claim can be voided along two distinct paths. An `Adjudicator` may void an `APPROVED` claim before any funds have moved: this sets `reimbursable_amount_cents` to zero, moves the claim from `APPROVED` to `VOIDED`, and increments its `version`; no ledger entry is produced because no cash had left the account. A `PlanAdmin` may instead claw back a `REIMBURSED` claim: this appends a compensating `REIMBURSEMENT_REVERSAL` `LedgerEntry` for the claim's `reimbursable_amount_cents`, recomputes the account's `reimbursed_cents` and `available_balance_cents`, and moves the claim to `VOIDED`. The clawback's balance restoration cascades: if the account had been `DEPLETED` and its balance is now positive, it returns from `DEPLETED` to `ACTIVE`; and if this clawed-back claim was the only unsubstantiated `REIMBURSED` claim on the account, the account's `compliance_hold` returns from `HELD` to `CLEAR`. The claim's `version` is incremented. `VOIDED` is terminal. Voiding a claim that is not in a state permitting the requested void path is rejected with `ERR_INVALID_STATE`.

### 3.8. Year-End Settlement: Forfeiture and Carryover

Settlement is the use-it-or-lose-it sweep. A `PlanAdmin` settles a plan year, which is permitted only while the plan year's `lifecycle` is `OPEN`; settling an already-`SETTLED` plan year is rejected with `ERR_INVALID_STATE`. Settlement may run only after the filing window has closed: the current server date must be strictly past `run_out_end` (and strictly past `grace_period_end` as well when the plan year elects `GRACE_PERIOD`). The server processes every eligible account under the plan year in `created_at` ascending order, and an account is eligible while its `funding_status` is `ACTIVE` or `DEPLETED` and its own effective filing deadline (its `run_out_end`, or its `grace_period_end` when it elects `GRACE_PERIOD`) has passed.

For each account, the unused balance swept is its `available_balance_cents` (cash on hand at settlement). An HSA forfeits nothing and carries nothing — HSA funds roll indefinitely — so both its forfeiture and its carryover are zero. A Health FSA under `CARRYOVER` performs a two-bucket waterfall: the carryover bucket is filled first to the smaller of the unused balance and `carryover_cap_cents`, and the remainder of the unused balance forfeits; its `forfeited_cents` is therefore the unused balance minus the carried-over amount. A Health FSA under `NONE` or `GRACE_PERIOD` carries nothing and forfeits the entire unused balance — a grace period only extended the earlier service window, it never preserved the dollars. A DCFSA always forfeits the entire unused balance and may never carry over, regardless of relief mode. The account's `forfeited_cents` and carryover linkage are recorded, and its `funding_status` moves to `CLOSED` (terminal), with its `version` incremented by one.

The cascades during settlement write the audit trail. When an account's `forfeited_cents` is greater than zero, a `FORFEITURE` `LedgerEntry` is appended to it. When a Health FSA carries a positive amount forward, a `CARRYOVER_OUT` `LedgerEntry` is appended on that source account, and then a new destination Health FSA `Account` is created for the same `participant_id` and the same `plan_year_id`, opened with `funding_status` `PENDING` and `elected_amount_cents` of zero, credited with `carried_in_cents` equal to the carried amount, and stamped with `carryover_source_account_id` pointing back at the source account; a `CARRYOVER_IN` `LedgerEntry` is then appended on that destination account. The destination is a carryover-holding account discoverable by listing accounts filtered on `carryover_source_account_id` equal to the source account's id. Once every eligible account is swept, the plan year's `lifecycle` moves from `OPEN` to `SETTLED` and the plan year's `version` is incremented by one.

### 3.9. Reading Accounts, Ledgers, and the Test Clock

All four roles may read individual resources and lists. Accounts can be listed and filtered by `participant_id`, by `plan_year_id`, by `carryover_source_account_id` (to find carryover-holding accounts), or by `account_type`. Claims can be listed and filtered by `account_id`, by `participant_id`, or by `status`. Contributions are listed under their account, and a claim's own ledger entries are listed under that claim. An account's full append-only audit trail is read by listing its ledger entries, optionally filtered by `entry_type`. Reimbursement batches can be listed and filtered by `participant_id`.

Because year-end settlement and the filing-window checks depend on the passage of time, the server's wall clock is itself an addressable control. A `PlanAdmin` advances it through a test-driving capability that sets `current_utc` on the singleton clock state to a supplied `to_iso8601` instant, making settlement and deadline behavior reachable deterministically. Until it is first set, `current_utc` holds the server's own boot-time wall clock. Every filing-deadline and settlement-eligibility comparison reads `current_utc` from this clock; because deadlines are calendar dates, those comparisons are made at date granularity (only the `YYYY-MM-DD` portion of `current_utc` participates), so the clock's "current server date" is the date component of `current_utc`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, settlement, contribution reversal, and disbursement — return `200 OK`. The request and response bodies are not restated here; reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/participants` | Register a participant | PlanAdmin |
| GET | `/participants/{id}` | Fetch a participant | PlanAdmin, Participant, Adjudicator, FundDisburser |
| GET | `/participants` | List participants | PlanAdmin |
| PATCH | `/participants/{id}` | Update mutable participant fields | PlanAdmin |
| POST | `/plan-years` | Create a plan year with caps and relief config | PlanAdmin |
| GET | `/plan-years/{id}` | Fetch a plan year | PlanAdmin, Participant, Adjudicator, FundDisburser |
| GET | `/plan-years` | List plan years | PlanAdmin |
| POST | `/plan-years/{id}/settle` | Run year-end settlement for eligible accounts | PlanAdmin |
| POST | `/accounts` | Open an account for a participant under a plan year | PlanAdmin |
| GET | `/accounts/{id}` | Fetch an account with computed balances | PlanAdmin, Participant, Adjudicator, FundDisburser |
| GET | `/accounts` | List accounts (filterable) | PlanAdmin, Participant, Adjudicator, FundDisburser |
| POST | `/accounts/{id}/activate` | Activate a PENDING account | PlanAdmin |
| POST | `/accounts/{id}/clear-hold` | Clear a compliance hold | PlanAdmin |
| POST | `/accounts/{id}/contributions` | Post a contribution (OCC-guarded) | PlanAdmin |
| GET | `/accounts/{id}/contributions` | List contributions for an account | PlanAdmin, Participant, Adjudicator, FundDisburser |
| POST | `/accounts/{id}/contributions/{contribution_id}/reverse` | Reverse a POSTED contribution (OCC-guarded) | PlanAdmin |
| POST | `/claims` | Submit a reimbursement claim | Participant, PlanAdmin |
| GET | `/claims/{id}` | Fetch a claim | PlanAdmin, Participant, Adjudicator, FundDisburser |
| GET | `/claims` | List claims (filterable) | PlanAdmin, Participant, Adjudicator, FundDisburser |
| POST | `/claims/{id}/adjudicate` | Approve, deny, or request docs on a claim | Adjudicator |
| POST | `/claims/{id}/resubmit` | Resubmit a pending-substantiation claim | Participant, PlanAdmin |
| POST | `/claims/{id}/void` | Void an approved claim or claw back a reimbursed one | Adjudicator, PlanAdmin |
| GET | `/claims/{id}/ledger-entries` | Read ledger entries produced by a claim | PlanAdmin, Participant, Adjudicator, FundDisburser |
| POST | `/reimbursement-batches` | Create a draft reimbursement batch | FundDisburser, PlanAdmin |
| GET | `/reimbursement-batches/{id}` | Fetch a reimbursement batch | PlanAdmin, FundDisburser |
| GET | `/reimbursement-batches` | List reimbursement batches (filterable) | PlanAdmin, FundDisburser |
| POST | `/reimbursement-batches/{id}/disburse` | Disburse a batch (OCC-guarded) | FundDisburser |
| GET | `/accounts/{id}/ledger-entries` | Read an account's append-only audit trail | PlanAdmin, Participant, Adjudicator, FundDisburser |
| POST | `/_clock/set_current_utc` | Set the server clock (test-driving) | PlanAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_ON_HOLD` | 409 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_EXPENSE_NOT_QUALIFIED` | 422 |
| `ERR_SERVICE_DATE_OUTSIDE_WINDOW` | 422 |
| `ERR_FILING_WINDOW_CLOSED` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_CONTRIBUTION_CAP_EXCEEDED` | 422 |
| `ERR_ELECTION_CAP_EXCEEDED` | 422 |
| `ERR_COVERAGE_WINDOW_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_FUNDS` | 422 |
| `ERR_RELIEF_MODE_CONFLICT` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
