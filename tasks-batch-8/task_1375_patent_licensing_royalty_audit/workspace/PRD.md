# Patent Licensing & Royalty Audit API — Product Requirements Document

## 1. Introduction

A technology licensing office lives or dies on two flows of money: royalties that licensees self-report under their license agreements, and the audit recoveries that follow when those reports do not hold up to scrutiny. Between the two sits a thicket of contractual machinery — royalty base definitions, running rates, minimum royalty floors, milestone fees, sublicense pass-through obligations, and most-favored-licensee clauses that ripple backwards through quarters of already-accepted reports. This document specifies the Patent Licensing & Royalty Audit API, the system of record for that machinery. It covers the full arc of the office's work: onboarding licensees, drafting and activating license agreements, tracking cumulative-sales and calendar milestones, approving sublicense grants, taking in periodic royalty reports and screening them against external benchmarks, exercising audit rights within a contractual lookback window, recording findings and assessing shortfalls, negotiating and ratifying settlements or proceeding to arbitration, and finally distributing recognized revenue to inventors according to their agreed shares.

The API is built around a small set of uncompromising guarantees. All money moves as integer cents through a deterministic revenue-recognition ledger, so a cent recognized on a report can be traced through the agreement's pool and into an inventor's distribution line. Calculations are fully deterministic: rounding points, evaluation order, and threshold inclusivity are pinned by specification, not left to implementation taste. Segregation of duties is enforced where the office's controls demand it — the counsel who ratifies a settlement may not be the analyst who opened the underlying audit, and the finance officer who approves a distribution may not be the one who created it. Time-dependent behavior (agreement expiry, date milestones, audit windows, most-favored-licensee lookbacks) is driven by a controllable logical clock rather than the wall clock. All endpoints are mounted under the `/licensing` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly five roles: `LicensingAnalyst`, `Licensee`, `LegalCounsel`, `FinanceOfficer`, and `IPAdmin`. A request with a missing header, or a role value outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles partition the office's work. A `LicensingAnalyst` runs the licensing desk: registering licensees, drafting and amending agreements, driving lifecycle actions, creating milestones, deciding sublicense grants, validating and accepting royalty reports, opening and advancing audits, and recording findings. A `Licensee` is the licensed company itself: it submits royalty reports, requests sublicense grants, accepts or disputes findings, and negotiates settlement offers on its own disputes. A `LegalCounsel` negotiates settlements, ratifies them, and records arbitration awards. A `FinanceOfficer` creates, approves, and voids inventor distribution runs. An `IPAdmin` is the platform administrator and operates only the logical clock, plus read access to the licensee and agreement collections.

Identity semantics differ by role and are contractual. When `X-User-Role` is `Licensee`, `X-User-ID` is the `id` of the acting `Licensee` entity; ownership checks on any resource that references a licensee compare the resource's `licensee_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule governs report submission, sublicense requests, finding acceptance, finding disputes, dispute offers and offer acceptance, and read access to the licensee's own record — a `Licensee` caller retrieving a licensee record other than its own is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `LicensingAnalyst`, `LegalCounsel`, `FinanceOfficer`, or `IPAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `opened_by_user_id` on an audit, `recorded_by_user_id` on a finding, `decided_by_user_id` on a sublicense grant, `ratified_by_user_id` on a dispute, or `created_by_user_id` / `approved_by_user_id` on a distribution run — but never compares it against any entity's `id`. Those recorded identifiers are not decorative: they anchor the segregation-of-duties checks described in §3.8 and §3.9.

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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many items are skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All nine resources in this system — licensees, license agreements, milestones, sublicense grants, royalty reports, royalty audits, audit findings, disputes, and distribution runs — share one set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on every mutation.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including mutations caused by cascades originating elsewhere.

Every resource in the system carries all four of these fields; there are no reduced-schema resources. Any state transition, derived-field recomputation, balance posting, or cascade hop that changes a resource counts as a mutation of that resource and therefore bumps its `version` and refreshes its `updated_at`.

### 2.5. Monetary Precision and Basis-Point Arithmetic

All monetary values in the system — reported sales, royalty bases, royalties, shortfalls, settlement and award amounts, milestone fees, distribution pools, and every balance — are integers denominated in cents. No floating-point money appears anywhere in the API. Rates and shares are expressed in basis points against a fixed denominator of ten thousand, so a `base_rate_bp` of 450 means 4.5 percent.

Rounding is pinned. Whenever a basis-point rate is applied to a cent amount, the product is divided by ten thousand and rounded half-up to a whole cent. Where a royalty has both a product component and a pass-through component, each component is rounded half-up separately first, and the two rounded components are then summed — the rounding order (per-component rounding before summation) is part of the contract. Aggregate checks that compare a cent amount against a basis-point-scaled threshold also round the threshold half-up to a whole cent, and every threshold comparison in the system is inclusive-pass on equality unless explicitly stated otherwise.

Rate and share fields carry fixed bounds. `base_rate_bp` must be strictly greater than 0 and at most 10000. `sublicense_passthrough_rate_bp` must be at least 0 and at most 10000. `underreport_tolerance_bp` must be at least 0 and strictly less than 10000. The `share_bp` values inside an agreement's `inventor_shares` must sum to exactly 10000.

### 2.6. The Logical Clock and Time-Driven Effects

The system never reads the wall clock. All time-dependent behavior — period closure, agreement expiry, date milestones, audit windows, and most-favored-licensee lookbacks — is evaluated against a server-held logical clock. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z.

An `IPAdmin`-only capability advances the logical clock by supplying a `to_iso8601` instant; the response echoes the resulting time as `current_utc`. Advancing the clock fires two automatic sweeps. First, every agreement in `ACTIVE` or `SUSPENDED` status whose `expiration_date` is strictly earlier than the new logical time transitions to `EXPIRED`, with the usual version increment. Second, every `PENDING` milestone of trigger type `DATE` whose `trigger_date` is on or before the new logical time is achieved: its `achieved_at` is set, its `fee_cents` accrues to the contracting licensee's outstanding balance, and its version increments.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, and for those two the version field is a mandatory, non-optional input.

Amending a license agreement requires the request to carry `expected_agreement_version`, holding the agreement `version` the client last observed. If the agreement's current `version` has advanced past that value — because a prior amendment or lifecycle action legitimately rewrote the agreement — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from overwriting terms it has not seen.

Submitting a settlement offer on a dispute requires the request to carry `expected_dispute_version`, holding the dispute `version` the client last observed. If the dispute's current `version` has advanced — because a prior offer legitimately superseded the pending round — the offer is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. Lifecycle actions, validations, acceptances, ratifications, and all other writes rely on their state-machine preconditions rather than client-supplied versions.

### 2.8. Validation Pipeline and Resource Resolution Order

Every request is validated against an ordered pipeline of check tiers. A request that fails an earlier tier never surfaces an error from a later tier — the first failing tier determines the response. The tiers, in evaluation order, are:

1. **Authentication.** `X-User-Role` must be present and name one of the five declared roles, and `X-User-ID` must be present; failures yield `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The role must be permitted on the target endpoint; failures yield `ERR_FORBIDDEN_ROLE`.
3. **Existence.** Path identifiers are resolved strictly left-to-right, and foreign-key references in the request body must exist. The first unresolvable reference produces the corresponding not-found error: `ERR_LICENSEE_NOT_FOUND` for a licensee, `ERR_AGREEMENT_NOT_FOUND` for a license agreement, `ERR_REPORT_NOT_FOUND` for a royalty report, `ERR_AUDIT_NOT_FOUND` for an audit, `ERR_FINDING_NOT_FOUND` for an audit finding, `ERR_DISPUTE_NOT_FOUND` for a dispute, `ERR_SUBLICENSE_NOT_FOUND` for a sublicense grant, and `ERR_RUN_NOT_FOUND` for a distribution run — each with HTTP 404.
4. **Licensee ownership.** A `Licensee`-role caller may act only on resources whose licensee is the caller; failures yield `ERR_NOT_RESOURCE_OWNER`.
5. **Request body schema.** Required fields must be present, types must be valid, enum values must be members of their declared sets, no undeclared fields may appear, and conditional-required rules must hold — a milestone's `threshold_cents` is required if and only if its `trigger_type` is `CUMULATIVE_SALES`, `trigger_date` is required if and only if it is `DATE`, and on report acceptance `adjusted_base_cents` is required if and only if the report is `FLAGGED` and forbidden when the report is `VALIDATED`. Failures yield `ERR_VALIDATION` (HTTP 400).
6. **Licensee standing.** Operations that require an `ACTIVE` licensee are checked here; failures yield `ERR_LICENSEE_NOT_ACTIVE` (HTTP 409).
7. **Agreement standing.** Operations that require the agreement in a particular status set are checked here; failures yield `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409).
8. **State-machine conformance.** The target resource must be in a state from which the requested transition exists. Failures yield the resource-appropriate state error: `ERR_REPORT_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_FINDING_NOT_OPEN`, `ERR_DISPUTE_INVALID_STATE`, `ERR_RUN_INVALID_STATE`, or `ERR_SUBLICENSE_INVALID_STATE` — all HTTP 409.
9. **Segregation of duties.** Maker-checker rules are evaluated after state conformance; failures yield `ERR_SOD_CONFLICT` (HTTP 409).
10. **Business constraints.** Overlap rules, share-sum integrity, sublicensing permission, tax identifier uniqueness, and own-offer acceptance rules: `ERR_REPORT_PERIOD_OVERLAP`, `ERR_AUDIT_SCOPE_OVERLAP`, `ERR_DUPLICATE_TAX_ID` (HTTP 409), and `ERR_SHARE_SUM_INVALID`, `ERR_SUBLICENSING_NOT_GRANTED`, `ERR_CANNOT_ACCEPT_OWN_OFFER` (HTTP 422).
11. **Temporal rules.** Periods must be closed and audit scopes must lie within the contractual window: `ERR_PERIOD_NOT_CLOSED` and `ERR_AUDIT_WINDOW_EXPIRED` (HTTP 422).
12. **Referential business rules.** Findings must point at examinable reports within scope, sublicense-revenue lines need an approved grant, and a report's declared licensee must match the agreement's licensee: `ERR_REPORT_NOT_IN_AUDIT_SCOPE` and `ERR_NO_APPROVED_SUBLICENSE` (HTTP 422), or `ERR_VALIDATION` (HTTP 400) for the licensee mismatch.
13. **Fiscal guards.** Last, the money-shaping rules: `ERR_ADJUSTMENT_NOT_UPWARD` and `ERR_POOL_EXCEEDS_UNDISTRIBUTED` (HTTP 422).

### 2.9. Financial Ledgers and Revenue Recognition Posting

The system maintains five monetary accumulators and treats them as a ledger: nothing appears in them without a posting event, and every posting event names its delta.

On the `Licensee`, `outstanding_balance_cents` is the receivable owed by the licensee. It accumulates, in order of event kind: the final royalty of every accepted report, the fee of every achieved milestone, the shortfall of every accepted audit finding, every ratified settlement amount, and every arbitration award. Compensating events subtract the same amounts. Separately, `credit_balance_cents` holds credits owed back to the licensee — today, the credits granted by retroactive most-favored-licensee adjustments.

On the `LicenseAgreement`, three accumulators track the revenue pipeline. `cumulative_accepted_base_cents` is the running sum of the final royalty bases of the agreement's accepted reports that have not been voided — the base used is `royalty_base_cents` for a plain acceptance and `adjusted_base_cents` for an acceptance with adjustment. `cumulative_recognized_revenue_cents` is the agreement's recognized revenue: accepted final royalties, plus accepted finding shortfalls, plus ratified settlements, plus arbitration awards, minus the final royalty of any voided acceptance. `undistributed_pool_cents` mirrors the same posting deltas as recognized revenue, and additionally is debited by a distribution run's `pool_cents` when the run is approved and credited back by the same amount if the run is later voided. The pool therefore always holds recognized revenue not yet consumed by a posted distribution.

All postings happen immediately, as part of the triggering operation, in integer cents. Every posting is a mutation of the entity holding the accumulator and bumps that entity's `version` per §2.4.

### 2.10. Cascades, Hops, and Compensating Reversals

Several operations in this API mutate more than one entity. Wherever that happens, the cascade is specified hop by hop: the primary mutation first, then each dependent mutation in its fixed order. Accepting a royalty report is the canonical example — it posts to the agreement's accumulators (hop 1), to the licensee's outstanding balance (hop 1b), then re-evaluates the agreement's pending milestones (hop 2), and accrues the fees of any milestones that tip over (hop 3). Activating an agreement may trigger a two-hop most-favored-licensee cascade onto other agreements and their licensees. Ratifying a settlement or recording an arbitration award resolves the underlying finding as part of the same operation.

The reverse discipline is symmetric: where an operation is voidable, the void is a compensating reversal that subtracts exactly what the original operation added, using the amounts recorded at the time — the adjusted base, not the original base, when the acceptance being voided was an adjusted one. Milestones that were achieved only because of the reversed amounts revert, and their fees un-accrue. No cascade ever leaves an entity's `version` untouched: every entity mutated at any hop increments its `version` by 1 and refreshes `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Licensee Onboarding and Commercial Standing

A `LicensingAnalyst` registers each contracting company as a **Licensee**, supplying its `legal_name`, `tax_id`, and `contact_email`. The tax identifier is unique across all licensees: a registration attempt reusing an existing `tax_id` is rejected with `ERR_DUPLICATE_TAX_ID` (HTTP 409). A new licensee starts in `ACTIVE` status with both `outstanding_balance_cents` and `credit_balance_cents` at zero.

Commercial standing is managed through a lifecycle action on the licensee record. The request carries an `action`: `SUSPEND` moves an `ACTIVE` licensee to `SUSPENDED`; `REINSTATE` returns a `SUSPENDED` licensee to `ACTIVE`; `TERMINATE` moves either an `ACTIVE` or a `SUSPENDED` licensee to `TERMINATED`, which is terminal. Each lifecycle action increments the licensee's `version` by 1.

Standing matters downstream. Submitting a royalty report and requesting a sublicense grant both require the licensee to be `ACTIVE`; either attempt on a `SUSPENDED` or `TERMINATED` licensee is rejected with `ERR_LICENSEE_NOT_ACTIVE`. The licensee collection can be listed with an optional `status` filter, and individual records can be fetched — for `Licensee`-role callers, only their own record, per the ownership rule of §2.1.

### 3.2. Drafting and Amending License Agreements

The **LicenseAgreement** is the commercial heart of the system. A `LicensingAnalyst` drafts one by naming the contracting licensee (`licensee_id`), the patent it covers (`patent_reference`, a publication reference such as US-10123456-B2, which also keys the most-favored-licensee sweep of §3.3), a `title`, the royalty base definition, the running rate, and the agreement's temporal bounds. The `royalty_base_definition` is either `NET_SALES` — the royalty base is the sum of gross sales minus deductions over the report's non-sublicense lines — or `GROSS_SALES` — the base is the sum of gross sales over those same lines, ignoring deductions. The `base_rate_bp` is the running royalty rate in basis points applied to that base. `minimum_period_royalty_cents` establishes a per-report royalty floor; it defaults to 0, which means no minimum. Sublicensing is configured by `sublicense_allowed` (default false) and `sublicense_passthrough_rate_bp` (default 0), the pass-through rate applied to sublicense-revenue lines. The most-favored-licensee configuration comprises `mfl_clause` (default false), `mfl_mode` (`RETROACTIVE` or `PROSPECTIVE`, default `RETROACTIVE`), and `mfl_lookback_quarters` (default 4, at least 1). Audit reach is set by `audit_window_months` (default 24, at least 1), and screening sensitivity by `underreport_tolerance_bp` (default 500). The agreement names its beneficiaries in `inventor_shares`, an array of entries each carrying an `inventor_name` and a `share_bp`; the shares must sum to exactly 10000 basis points and each `inventor_name` must be unique within the agreement — a submission violating either rule is rejected with `ERR_SHARE_SUM_INVALID` (HTTP 422). Finally, `effective_date` and `expiration_date` bound the agreement's life, and the expiration must be strictly later than the effective date.

A new agreement starts in `DRAFT`. While an agreement is `DRAFT` or `ACTIVE`, a `LicensingAnalyst` may amend its commercial terms: the royalty base definition, running rate, minimum floor, sublicense flag and pass-through rate, the MFL configuration, the audit window, the screening tolerance, the inventor shares, and the expiration date. The contracting licensee, patent reference, title, and effective date are fixed at creation and cannot be amended. Every amendment must carry `expected_agreement_version` per §2.7, increments the agreement's `version` by 1, and re-enforces the share-sum rule when `inventor_shares` is part of the amendment.

Two computed fields track the agreement's rate posture. `mfl_adjusted_rate_bp` holds the effective first-line rate after a most-favored-licensee adjustment; while it is null, `base_rate_bp` is the rate in effect. `last_mfl_credit_cents` records the credit granted by the most recent retroactive adjustment and starts at 0. Three further accumulators — `cumulative_accepted_base_cents`, `cumulative_recognized_revenue_cents`, and `undistributed_pool_cents` — are the ledger positions of §2.9, fed by the posting events described in §3.6 through §3.9.

Agreements gate nearly every downstream operation by status. Royalty report submission and sublicense requests require the agreement `ACTIVE`. Milestone creation is permitted while the agreement is `DRAFT` or `ACTIVE`. Audits and distribution runs may target an agreement in any status other than `DRAFT`. Any of these operations attempted against an agreement outside its permitted status set is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). The agreement collection can be listed with optional `licensee_id`, `status`, and `patent_reference` filters.

### 3.3. Activation and the Most-Favored-Licensee Sweep

Lifecycle actions on an agreement carry an `action` and are performed by a `LicensingAnalyst`. `ACTIVATE` moves a `DRAFT` agreement to `ACTIVE`, and is permitted only when the agreement is `DRAFT`, its licensee is `ACTIVE`, and its `expiration_date` lies strictly in the future relative to the current logical time; a violation of the state precondition surfaces as the appropriate state or standing error of §2.8. `SUSPEND` moves `ACTIVE` to `SUSPENDED`, `REINSTATE` returns `SUSPENDED` to `ACTIVE`, and `TERMINATE` moves either `ACTIVE` or `SUSPENDED` to `TERMINATED`. The remaining terminal status, `EXPIRED`, is never set by a client: it is reached only through the clock sweep of §2.6. Every lifecycle transition increments the agreement's `version` by 1.

Activation carries a side effect no other transition has: the **most-favored-licensee sweep**. When an agreement is activated, the system examines every other agreement covering the same `patent_reference` that is currently `ACTIVE` and carries `mfl_clause` set to true. For each such agreement whose effective rate — its `mfl_adjusted_rate_bp` if one is set, otherwise its `base_rate_bp` — exceeds the newly activated agreement's `base_rate_bp`, the clause fires: the existing agreement's `mfl_adjusted_rate_bp` is set down to the new agreement's base rate, so the favored licensee enjoys the better rate from that moment forward. Affected agreements are processed in their creation order, earliest first. The sweep only ever lowers rates; an existing agreement already enjoying an equal or lower effective rate is untouched.

What happens next depends on the affected agreement's `mfl_mode`. Under `PROSPECTIVE`, the rate change is the whole remedy: `last_mfl_credit_cents` stays at 0 and no money moves. Under `RETROACTIVE`, the office also makes the favored licensee whole for the recent past. The lookback window opens at the current logical time minus three months per quarter of the agreement's `mfl_lookback_quarters` — four quarters means a twelve-month window. Every one of the affected agreement's reports in `ACCEPTED` or `ACCEPTED_WITH_ADJUSTMENT` status whose `accepted_at` falls on or after that window start is re-priced at the new rate: the product component is recomputed as the report's base — its `adjusted_base_cents` when one was set, otherwise its `royalty_base_cents` — multiplied by the new rate over ten thousand, rounded half-up; the pass-through component is the report's `sublicense_net_sales_cents` multiplied by the agreement's `sublicense_passthrough_rate_bp` over ten thousand, rounded half-up; the recomputed final royalty is the greater of those two components' sum and the agreement's `minimum_period_royalty_cents`. The per-report credit is the excess of the originally recognized `final_royalty_cents` over this recomputed amount, floored at zero. The credits sum to the agreement's new `last_mfl_credit_cents`, and that same total is added to the contracting licensee's `credit_balance_cents` — a second hop of the activation cascade, after the rate adjustment itself.

### 3.4. Milestones: Sales Thresholds and Calendar Triggers

A **Milestone** hangs a one-time fee off an agreement's progress. A `LicensingAnalyst` creates one — while the parent agreement is `DRAFT` or `ACTIVE` — by supplying `agreement_id`, a `name`, a `trigger_type`, and a `fee_cents` amount that is at least 0. The trigger type is `CUMULATIVE_SALES` or `DATE`. For `CUMULATIVE_SALES`, `threshold_cents` is required and must be strictly greater than 0: the milestone is achieved when the agreement's `cumulative_accepted_base_cents` reaches the threshold. For `DATE`, `trigger_date` is required: the milestone is achieved when the logical clock reaches that date. Supplying the field that does not belong to the chosen trigger type, or omitting the one that does, violates the conditional-required schema rule and is rejected with `ERR_VALIDATION`. A new milestone starts `PENDING`, with `achieved_at` null.

Achievement is automatic and inclusive at the boundary. After every royalty report acceptance, the agreement's `PENDING` milestones are examined in their creation order, earliest first, and each `CUMULATIVE_SALES` milestone whose `threshold_cents` is less than or equal to the updated cumulative accepted base is achieved — a cumulative total exactly equal to the threshold achieves. Advancing the logical clock achieves every `PENDING` `DATE` milestone whose `trigger_date` is on or before the new time. Achievement sets `achieved_at`, adds the milestone's `fee_cents` to the contracting licensee's `outstanding_balance_cents` — the fee-accrual hop of the acceptance cascade — and increments the milestone's `version`. `ACHIEVED` is the terminal state for milestones reached through the clock.

Sales-based achievement is not necessarily permanent. When a report acceptance is voided and the agreement's cumulative accepted base falls strictly below the threshold of an already-achieved `CUMULATIVE_SALES` milestone, that milestone reverts from `ACHIEVED` back to `PENDING`: `achieved_at` is cleared, the previously accrued `fee_cents` is subtracted from the licensee's `outstanding_balance_cents` as a compensating reversal, and the milestone's `version` increments. Only cumulative-sales milestones can revert; a date milestone, once achieved, stays achieved. Milestones can be listed per agreement through a required `agreement_id` filter, optionally narrowed by `status`.

### 3.5. Sublicense Grants and Pass-Through Obligations

Where an agreement permits it, a licensee may extend rights downstream. The `Licensee` requests a **SublicenseGrant** by supplying the `agreement_id`, the `sublicensee_name`, and the `territory` scope (for example EU or NA). Three standing rules gate the request, in the pipeline order of §2.8: the requesting licensee must be `ACTIVE`, the agreement must be `ACTIVE`, and the agreement's `sublicense_allowed` must be true — the last violation is rejected with `ERR_SUBLICENSING_NOT_GRANTED` (HTTP 422). As an ownership rule, a licensee may only request grants under its own agreements. A new grant starts `PENDING`.

Decisions belong to the `LicensingAnalyst`, who records a `decision` on the grant. From `PENDING`, the grant may be decided `APPROVED` or `REJECTED`; an `APPROVED` grant may later be decided `REVOKED`. `REJECTED` and `REVOKED` are terminal. Any decision attempted from a state that does not support it — approving an already-approved grant, revoking a pending one — is rejected with `ERR_SUBLICENSE_INVALID_STATE` (HTTP 409). Each decision stamps the grant's `decided_by_user_id` with the deciding analyst's identity and increments the grant's `version`.

The grant's commercial effect appears at report time: a royalty report line flagged as sublicense revenue is only legitimate if the agreement holds at least one `APPROVED` grant, and such lines feed the pass-through royalty component rather than the product royalty base, as detailed in §3.6. Grants can be listed under a required `agreement_id` filter with an optional `status` filter; `Licensee`-role readers see only grants under their own agreements.

### 3.6. Royalty Report Intake, Screening, and Acceptance

The periodic royalty report is where licensees account for their sales. A `Licensee` submits a **RoyaltyReport** with the `agreement_id`, its own `licensee_id`, the reporting window `period_start` and `period_end`, and a non-empty `lines` array. The declared `licensee_id` must be the agreement's contracting licensee and must match the caller's identity; a report naming a different licensee than the agreement's is rejected with `ERR_VALIDATION`, while a caller submitting under another licensee's identity violates the ownership rule. Both the licensee and the agreement must be `ACTIVE`. The window must be well-formed: `period_end` strictly later than `period_start`, and not later than the current logical time — a period that has not closed yet is rejected with `ERR_PERIOD_NOT_CLOSED` (HTTP 422). Each line carries a `product_label`, a `units_sold` count of at least 0, a `gross_sales_cents` of at least 0, a `deductions_cents` of at least 0 and never exceeding that line's gross sales, and an `is_sublicense_revenue` flag defaulting to false. If any line is flagged as sublicense revenue, the agreement must hold at least one `APPROVED` sublicense grant; otherwise the submission is rejected with `ERR_NO_APPROVED_SUBLICENSE` (HTTP 422).

One report per period, per agreement. The submitted window is treated as half-open — inclusive at `period_start`, exclusive at `period_end` — and must not overlap any existing report of the same agreement in `SUBMITTED`, `VALIDATED`, `FLAGGED`, `ACCEPTED`, `ACCEPTED_WITH_ADJUSTMENT`, or `AUDIT_REFERRED` status. Two periods that merely touch, one's start equal to the other's end, do not overlap. A colliding submission is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409).

At intake the server derives the report's financial picture. `reported_gross_sales_cents` sums gross sales over all lines; `reported_net_sales_cents` sums gross minus deductions over all lines. The `royalty_base_cents` follows the agreement's `royalty_base_definition` but counts only non-sublicense lines: for `NET_SALES`, the sum of gross minus deductions over those lines; for `GROSS_SALES`, the sum of gross alone over those lines. `sublicense_net_sales_cents` sums gross minus deductions over the sublicense-revenue lines only. The `provisional_royalty_cents` is then computed with no minimum floor: the product component is `royalty_base_cents` multiplied by the effective rate — `mfl_adjusted_rate_bp` if one is set on the agreement, otherwise `base_rate_bp` — over ten thousand, rounded half-up; the pass-through component is `sublicense_net_sales_cents` multiplied by `sublicense_passthrough_rate_bp` over ten thousand, rounded half-up; the provisional royalty is the sum of the two rounded components. The report is born in `SUBMITTED` status.

Intake screening is an analyst function. A `LicensingAnalyst` validates a `SUBMITTED` report by supplying a `benchmark_net_sales_cents` figure from an external benchmark, which the server records on the report. The screening threshold is the benchmark multiplied by ten thousand minus the agreement's `underreport_tolerance_bp`, divided by ten thousand, rounded half-up to a whole cent. If the report's `reported_net_sales_cents` is at least the threshold — equality passes — the report advances to `VALIDATED`; if it falls strictly below, the report is marked `FLAGGED`. Either way the benchmark is stored and the report's `version` increments; attempting to validate a report in any other state is rejected with `ERR_REPORT_INVALID_STATE`.

Acceptance is where money starts to move, and it has two paths. For a `VALIDATED` report, the analyst accepts it as filed — the request must not contain `adjusted_base_cents`. For a `FLAGGED` report, the analyst accepts with adjustment, and `adjusted_base_cents` is mandatory; adjustments are upward only, so the adjusted base must be strictly greater than the report's `royalty_base_cents`, with violations rejected as `ERR_ADJUSTMENT_NOT_UPWARD` (HTTP 422). Per the pipeline of §2.8, the request's shape is checked first (the conditional presence of `adjusted_base_cents` is a schema rule), then the report's state, and the upward-only fiscal rule applies last. On either path the final royalty is computed under the floor: the same two rounded components as the provisional calculation — but with `adjusted_base_cents` standing in for `royalty_base_cents` on the adjustment path — and `final_royalty_cents` is the greater of that sum and the agreement's `minimum_period_royalty_cents`. Acceptance stamps `accepted_at` with the current logical time (the timestamp the retroactive MFL lookback later reads), moves the report to `ACCEPTED` or `ACCEPTED_WITH_ADJUSTMENT`, and increments its `version`.

Acceptance then cascades, hop by hop per §2.10. Hop 1 posts to the agreement: `cumulative_accepted_base_cents` increases by the accepted base (`adjusted_base_cents` on the adjustment path, `royalty_base_cents` otherwise), while `cumulative_recognized_revenue_cents` and `undistributed_pool_cents` each increase by `final_royalty_cents`. Hop 1b posts to the licensee: `outstanding_balance_cents` increases by `final_royalty_cents`. Hop 2 re-runs the milestone check of §3.4 against the updated cumulative, and hop 3 accrues the fees of any milestones thereby achieved.

An acceptance can be undone through void-acceptance, which carries a `reason` and is performed by a `LicensingAnalyst`. Only an `ACCEPTED` or `ACCEPTED_WITH_ADJUSTMENT` report can be voided, and only while no audit finding referencing the report is `OPEN` or `DISPUTED` — a blocked or out-of-state attempt is rejected with `ERR_REPORT_INVALID_STATE`. The void is a true compensating reversal: every acceptance posting is subtracted with the amounts originally recorded — the adjusted base where one was used — the licensee's outstanding balance is relieved of the final royalty, milestones that fall strictly below their thresholds revert as in §3.4 with their fees un-accrued, and the report lands in `VOIDED` with another version increment. Reports can be listed with optional `agreement_id`, `licensee_id`, and `status` filters.

### 3.7. Audits, Findings, and Shortfall Assessment

When screening or suspicion warrants it, the office exercises its audit rights. A `LicensingAnalyst` opens a **RoyaltyAudit** by naming the `agreement_id` and the examination window `scope_period_start` to `scope_period_end`. The agreement must not be `DRAFT`. The scope is a closed interval — both endpoints included — so `scope_period_end` must be on or after `scope_period_start`. The contractual audit window bounds how far back the examination may reach: the scope's end must fall on or after the cutoff computed as the current logical time minus the agreement's `audit_window_months`; a scope ending exactly on the cutoff is still auditable, while an older scope is rejected with `ERR_AUDIT_WINDOW_EXPIRED` (HTTP 422). One audit per stretch of history at a time: the closed scope interval must not overlap any existing audit of the same agreement in `INITIATED`, `FIELDWORK`, or `FINDINGS_ISSUED` status — and because the interval is closed, two scopes that merely touch at an endpoint do overlap. A collision is rejected with `ERR_AUDIT_SCOPE_OVERLAP` (HTTP 409).

Opening an audit has a conditional cascade. Every report of the same agreement still sitting in `FLAGGED` status whose half-open reporting period intersects the closed audit scope is swept into `AUDIT_REFERRED`, with its `version` incremented — the report is now formally part of the examination and can no longer be accepted through the ordinary path. The audit itself starts in `INITIATED`, and the opener's identity is stamped into `opened_by_user_id`, where it will later anchor the settlement segregation-of-duties check.

The audit advances through a fixed corridor driven by an analyst-supplied `to_state`: from `INITIATED` to `FIELDWORK`, from `FIELDWORK` to `FINDINGS_ISSUED`, and from `FINDINGS_ISSUED` to `CLOSED`. Any other jump is rejected with `ERR_AUDIT_INVALID_STATE` (HTTP 409). Closing carries an additional gate: every finding recorded under the audit must have reached a terminal status — `ACCEPTED`, `WAIVED`, or `RESOLVED` — before the audit can close; attempting to close with findings still `OPEN` or `DISPUTED` is likewise rejected with `ERR_AUDIT_INVALID_STATE`. Each advance increments the audit's `version`.

Findings are recorded during fieldwork. While the audit is in `FIELDWORK` — and only then, otherwise `ERR_AUDIT_INVALID_STATE` — an analyst records an **AuditFinding** with the `audit_id`, the `report_id` under examination, a `finding_type`, and the `audited_base_cents` the examiner has determined, which must be at least 0. The finding type is one of `UNDERREPORTED_BASE`, `RATE_MISAPPLICATION`, `DEDUCTION_ABUSE`, or `MISSING_PASS_THROUGH`. The referenced report must be examinable: it must belong to the audit's agreement, its period must overlap the audit's scope, and it must be in `FLAGGED`, `AUDIT_REFERRED`, `ACCEPTED`, or `ACCEPTED_WITH_ADJUSTMENT` status — any shortfall there is rejected with `ERR_REPORT_NOT_IN_AUDIT_SCOPE` (HTTP 422). The system then computes the `shortfall_cents`. The amount already recognized for the report is its `final_royalty_cents` if the report was accepted or accepted with adjustment, and 0 otherwise. The royalty is then recomputed under the final-royalty rules of §3.6 with `audited_base_cents` standing in for the product base — the agreement's currently effective rate and minimum floor apply, and the report's original pass-through component is retained unchanged. The shortfall is the excess of the recomputed royalty over the recognized amount, floored at zero. The finding is born `OPEN`, with `recorded_by_user_id` stamped from the analyst's identity.

Resolving a finding takes one of three routes, and a finding in any status other than `OPEN` rejects both resolution and dispute attempts with `ERR_FINDING_NOT_OPEN` (HTTP 409). The resolution request carries a `resolution` value. The owning `Licensee` may accept the finding — `resolution` of `ACCEPTED` — which posts the `shortfall_cents` three ways at once: added to the licensee's `outstanding_balance_cents`, and added to both the agreement's `cumulative_recognized_revenue_cents` and `undistributed_pool_cents`. A `LicensingAnalyst` may instead waive the finding — `resolution` of `WAIVED` — which closes it with no financial effect. Or the owning licensee may dispute it, which is where §3.8 begins. Resolution and acceptance attempts by a licensee other than the finding's owner fail the ownership rule. Findings can be listed with optional `audit_id`, `report_id`, and `status` filters.

### 3.8. Dispute Negotiation, Settlement, and Arbitration

Disputing an `OPEN` finding is a `Licensee` right, restricted to the licensee that owns the finding's report. The dispute action moves the finding to `DISPUTED` and creates a **Dispute** in `OPEN` status in the same breath, with `finding_id`, `agreement_id`, and `licensee_id` all derived from the finding, its audit's agreement, and that agreement's licensee — none of them are supplied by the caller.

Negotiation proceeds through offers. A dispute's `offers` array is append-only; each entry records the `amount_cents` offered, the `offered_by_role`, the `offered_by_user_id`, a per-offer status of `PENDING`, `SUPERSEDED`, or `ACCEPTED`, and its `created_at`. At most one offer may be `PENDING` at a time, and submitting a new offer supersedes whatever offer is currently pending. Every offer submission carries `amount_cents` and must carry `expected_dispute_version` per §2.7 — a client negotiating off a stale view of the dispute is rejected with `ERR_STALE_VERSION`.

Offers move the dispute's state machine in a way that tracks who holds the pen. From `OPEN`, an offer by `LegalCounsel` moves the dispute to `NEGOTIATION`; an offer by the owning `Licensee` moves it to `COUNTERED`. From `NEGOTIATION`, a licensee counter-offer moves the dispute to `COUNTERED`, while counsel revising its own pending offer leaves the dispute in `NEGOTIATION`. From `COUNTERED`, a counsel counter-offer moves the dispute back to `NEGOTIATION`, while the licensee revising its own pending offer leaves it in `COUNTERED`. In every case the previously pending offer becomes `SUPERSEDED`, the new offer is appended as `PENDING`, and the dispute's `version` increments. A `Licensee` may only act on its own disputes, per the ownership rule. An offer attempted from any other dispute status is rejected with `ERR_DISPUTE_INVALID_STATE` (HTTP 409).

An offer is accepted by the counterparty, never by its author. Acceptance requires the dispute to be in `NEGOTIATION` or `COUNTERED` with exactly one `PENDING` offer on the table. From `NEGOTIATION`, the pending offer is counsel's, and only the owning `Licensee` may accept it; from `COUNTERED`, the pending offer is the licensee's, and only `LegalCounsel` may accept it. An acceptance attempted by the same role that made the pending offer is rejected with `ERR_CANNOT_ACCEPT_OWN_OFFER` (HTTP 422); any other state violation draws `ERR_DISPUTE_INVALID_STATE`. Acceptance marks the offer `ACCEPTED`, copies its amount into the dispute's `settlement_amount_cents`, moves the dispute to `RATIFICATION_PENDING`, and increments its version.

Settlement is not final until ratified. From `RATIFICATION_PENDING`, a `LegalCounsel` ratifies — subject to segregation of duties: the ratifying counsel's identity must differ from the `opened_by_user_id` of the audit that produced the finding, and a conflict is rejected with `ERR_SOD_CONFLICT` (HTTP 409). Ratification stamps `ratified_by_user_id`, moves the dispute to `SETTLED`, resolves the underlying finding from `DISPUTED` to `RESOLVED`, and posts `settlement_amount_cents` to all three ledger positions: the licensee's `outstanding_balance_cents`, and the agreement's `cumulative_recognized_revenue_cents` and `undistributed_pool_cents`.

The alternative ending is binding arbitration. From `NEGOTIATION` or `COUNTERED`, a `LegalCounsel` may record an arbitration by supplying an `awarded_amount_cents` of at least 0. Any pending offer is superseded, the dispute moves to `ARBITRATED`, the finding resolves from `DISPUTED` to `RESOLVED`, and the awarded amount posts to the same three ledger positions as a settlement would. Both `SETTLED` and `ARBITRATED` are terminal. Disputes can be listed with optional `finding_id`, `agreement_id`, `licensee_id`, and `status` filters.

### 3.9. Inventor Share Distribution

Recognized revenue ultimately belongs to the inventors. A `FinanceOfficer` creates a **DistributionRun** by naming the `agreement_id`, the `period_start` and `period_end` it covers, and the `pool_cents` to distribute. The agreement must not be `DRAFT`. The period must be well-formed — `period_end` strictly after `period_start` — and closed: a `period_end` later than the current logical time is rejected with `ERR_PERIOD_NOT_CLOSED`. The pool must be strictly greater than 0 and must not exceed the agreement's `undistributed_pool_cents` at creation; an oversized pool is rejected with `ERR_POOL_EXCEEDS_UNDISTRIBUTED` (HTTP 422). The run is born in `DRAFT` with `created_by_user_id` stamped from its creator.

Approval is a second pair of eyes. A `FinanceOfficer` approves a `DRAFT` run — anything else draws `ERR_RUN_INVALID_STATE` (HTTP 409) — and the approver must not be the run's creator: if the caller's identity equals `created_by_user_id`, the approval is rejected with `ERR_SOD_CONFLICT`. Because the pool may have changed since creation, the pool check runs again at approval against the agreement's current `undistributed_pool_cents`, and an exhausted pool is again rejected with `ERR_POOL_EXCEEDS_UNDISTRIBUTED`.

Approval freezes the run's `lines`: one per entry of the agreement's `inventor_shares`, preserving that array's order, each line recording the `inventor_name`, the `share_bp`, and the computed `amount_cents`. The allocation is a waterfall with pinned rounding. Each line's preliminary amount is the run's `pool_cents` multiplied by that inventor's `share_bp` over ten thousand, rounded half-up. The remainder is the pool minus the sum of the preliminary amounts — a small integer, never larger in magnitude than the number of shares. If the remainder is positive, one cent is added to each of the first `remainder` entries when the shares are ordered by `share_bp` descending with ties broken by `inventor_name` in ascending lexicographic order. If the remainder is negative, one cent is subtracted from each of the first entries of that same ordering taken in reverse — smallest share first — until the shortfall is absorbed. The invariant is exact: the line amounts sum to `pool_cents`, cent for cent. Approval also stamps `approved_by_user_id`, debits `pool_cents` from the agreement's `undistributed_pool_cents`, moves the run to `POSTED`, and increments its `version`.

A posted run can still be unwound: voiding a `POSTED` run — the request carries a `reason` — moves it to the terminal `VOIDED` status and restores the pool by adding `pool_cents` back to the agreement's `undistributed_pool_cents`. Only `POSTED` runs can be voided; any other attempt draws `ERR_RUN_INVALID_STATE`. Distribution runs can be listed with optional `agreement_id` and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Reads return `200 OK`. The table below is a summary only — request fields, response payloads, preconditions, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/licensing/licensees` | Create a licensee | LicensingAnalyst |
| GET | `/licensing/licensees` | List licensees | LicensingAnalyst, LegalCounsel, FinanceOfficer, IPAdmin |
| GET | `/licensing/licensees/{id}` | Get a licensee; Licensee role restricted to own id | LicensingAnalyst, LegalCounsel, FinanceOfficer, Licensee |
| POST | `/licensing/licensees/{id}/lifecycle` | Licensee lifecycle action (SUSPEND, REINSTATE, TERMINATE) | LicensingAnalyst |
| POST | `/licensing/license-agreements` | Create a license agreement in DRAFT | LicensingAnalyst |
| GET | `/licensing/license-agreements` | List agreements with filters | LicensingAnalyst, LegalCounsel, FinanceOfficer, Licensee, IPAdmin |
| GET | `/licensing/license-agreements/{id}` | Get one agreement; Licensee restricted to own agreements | LicensingAnalyst, LegalCounsel, FinanceOfficer, Licensee |
| PATCH | `/licensing/license-agreements/{id}` | Amend agreement terms while DRAFT or ACTIVE; OCC-guarded | LicensingAnalyst |
| POST | `/licensing/license-agreements/{id}/lifecycle` | Agreement lifecycle action; ACTIVATE runs the MFL sweep | LicensingAnalyst |
| POST | `/licensing/milestones` | Create a milestone on a DRAFT or ACTIVE agreement | LicensingAnalyst |
| GET | `/licensing/milestones` | List milestones for an agreement | LicensingAnalyst, LegalCounsel, FinanceOfficer, Licensee |
| GET | `/licensing/milestones/{id}` | Get one milestone | LicensingAnalyst, LegalCounsel, FinanceOfficer, Licensee |
| POST | `/licensing/sublicense-grants` | Licensee requests a sublicense grant | Licensee |
| GET | `/licensing/sublicense-grants` | List sublicense grants for an agreement | LicensingAnalyst, LegalCounsel, Licensee |
| GET | `/licensing/sublicense-grants/{id}` | Get one sublicense grant; Licensee restricted to own agreements' grants | LicensingAnalyst, LegalCounsel, Licensee |
| POST | `/licensing/sublicense-grants/{id}/decision` | Analyst decision: APPROVED or REJECTED from PENDING, REVOKED from APPROVED | LicensingAnalyst |
| POST | `/licensing/royalty-reports` | Licensee submits a royalty report with lines; provisional royalty computed | Licensee |
| GET | `/licensing/royalty-reports` | List royalty reports | LicensingAnalyst, LegalCounsel, FinanceOfficer, Licensee |
| GET | `/licensing/royalty-reports/{id}` | Get one report; Licensee restricted to own reports | LicensingAnalyst, LegalCounsel, FinanceOfficer, Licensee |
| POST | `/licensing/royalty-reports/{id}/validate` | Analyst validates intake against a benchmark; outcome VALIDATED or FLAGGED | LicensingAnalyst |
| POST | `/licensing/royalty-reports/{id}/accept` | Accept a VALIDATED report, or a FLAGGED report with an upward-only adjusted base | LicensingAnalyst |
| POST | `/licensing/royalty-reports/{id}/void-acceptance` | Compensating reversal of an acceptance | LicensingAnalyst |
| POST | `/licensing/audits` | Open a royalty audit; overlapping FLAGGED reports become AUDIT_REFERRED | LicensingAnalyst |
| GET | `/licensing/audits` | List audits | LicensingAnalyst, LegalCounsel |
| GET | `/licensing/audits/{id}` | Get one audit | LicensingAnalyst, LegalCounsel |
| POST | `/licensing/audits/{id}/advance` | Advance the audit through INITIATED, FIELDWORK, FINDINGS_ISSUED, CLOSED | LicensingAnalyst |
| POST | `/licensing/audit-findings` | Record a finding during FIELDWORK; shortfall computed | LicensingAnalyst |
| GET | `/licensing/audit-findings` | List findings | LicensingAnalyst, LegalCounsel, Licensee |
| GET | `/licensing/audit-findings/{id}` | Get one finding; Licensee restricted to own findings | LicensingAnalyst, LegalCounsel, Licensee |
| POST | `/licensing/audit-findings/{id}/resolution` | Resolve a finding: ACCEPTED by the owning Licensee, WAIVED by an analyst | LicensingAnalyst, Licensee |
| POST | `/licensing/audit-findings/{id}/dispute` | Licensee disputes a finding; creates the Dispute | Licensee |
| GET | `/licensing/disputes` | List disputes | LicensingAnalyst, LegalCounsel, Licensee |
| GET | `/licensing/disputes/{id}` | Get one dispute; Licensee restricted to own disputes | LicensingAnalyst, LegalCounsel, Licensee |
| POST | `/licensing/disputes/{id}/offers` | Submit a settlement offer; supersedes any pending offer; OCC-guarded | LegalCounsel, Licensee |
| POST | `/licensing/disputes/{id}/accept-offer` | Counterparty accepts the pending offer | LegalCounsel, Licensee |
| POST | `/licensing/disputes/{id}/ratify` | Counsel ratifies the settlement; SoD against the audit opener | LegalCounsel |
| POST | `/licensing/disputes/{id}/arbitrate` | Record a binding arbitration award | LegalCounsel |
| POST | `/licensing/distribution-runs` | Create an inventor distribution run in DRAFT | FinanceOfficer |
| GET | `/licensing/distribution-runs` | List distribution runs | FinanceOfficer, LicensingAnalyst |
| GET | `/licensing/distribution-runs/{id}` | Get one distribution run | FinanceOfficer, LicensingAnalyst |
| POST | `/licensing/distribution-runs/{id}/approve` | Approve and post the run; approver must differ from creator; freezes lines | FinanceOfficer |
| POST | `/licensing/distribution-runs/{id}/void` | Void a POSTED run and restore the undistributed pool | FinanceOfficer |
| POST | `/licensing/_clock/set_current_utc` | Advance the logical clock; expires agreements and achieves DATE milestones | IPAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_LICENSEE_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_SUBLICENSE_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_LICENSEE_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_REPORT_INVALID_STATE` | 409 |
| `ERR_AUDIT_INVALID_STATE` | 409 |
| `ERR_FINDING_NOT_OPEN` | 409 |
| `ERR_DISPUTE_INVALID_STATE` | 409 |
| `ERR_RUN_INVALID_STATE` | 409 |
| `ERR_SUBLICENSE_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SOD_CONFLICT` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_AUDIT_SCOPE_OVERLAP` | 409 |
| `ERR_SHARE_SUM_INVALID` | 422 |
| `ERR_SUBLICENSING_NOT_GRANTED` | 422 |
| `ERR_DUPLICATE_TAX_ID` | 409 |
| `ERR_CANNOT_ACCEPT_OWN_OFFER` | 422 |
| `ERR_PERIOD_NOT_CLOSED` | 422 |
| `ERR_AUDIT_WINDOW_EXPIRED` | 422 |
| `ERR_REPORT_NOT_IN_AUDIT_SCOPE` | 422 |
| `ERR_NO_APPROVED_SUBLICENSE` | 422 |
| `ERR_ADJUSTMENT_NOT_UPWARD` | 422 |
| `ERR_POOL_EXCEEDS_UNDISTRIBUTED` | 422 |
