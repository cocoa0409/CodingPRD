# Supplier Diversity Tier-2 API — Product Requirements Document

## 1. Introduction

Corporate procurement organizations that operate a supplier diversity program carry a dual obligation. Internally, the diversity office must demonstrate to business-unit leadership that sourcing decisions meaningfully include certified diverse suppliers, that spend is actually flowing to those suppliers, and that primes are honoring their subcontracting commitments. Externally, customers and government contracting officers demand periodic, defensible reports of diverse spend, often under both accrual-basis and cash-basis accounting conventions. The system described here is the API backbone for that office: it tracks suppliers and their diversity certifications, ingests spend, collects tier-2 subcontracting reports from prime contractors, sets program goals, produces quarterly scorecards, governs inclusion requirements on sourcing events, runs development engagements for capacity-constrained diverse suppliers, and audits the self-certification claims that underpin the whole program.

Several design tensions shape the requirements below. First, segregation of duties is enforced structurally: the analyst who submits a certification may not be the one who verifies it, the analyst who creates a goal may not publish it, and an auditor may never audit a certification they personally verified. Second, two parallel risk postures are maintained for every supplier — a STANDARD score shown to business units that reflects confirmed findings only, and a CONSERVATIVE score used by the compliance office that additionally weighs pending signals. Third, spend can be measured on either an accrual or a cash basis, and the choice is locked into each scorecard at generation time so that a published customer-facing report is never silently recomputed under a different convention. Fourth, a logical clock drives certification expiration and engagement activation so that the system can be exercised deterministically; the clock starts at a fixed instant and never consults wall-clock time on its own.

This document is the complete specification an implementing engineer needs. §2 lays out cross-cutting rules — envelope, pagination, identity, OCC, precision — that apply to every endpoint. §3 walks the business workflows in narrative form and is where nearly every validation, calculation, side effect, and state transition is specified; readers should expect a rule that governs one endpoint to be introduced next to the business event it protects, not in a centralized table. §4 is a compact endpoint index and §5 is the error code catalogue; neither repeats the conditions already given in §2 and §3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role the principal is acting in. A request missing either header, or carrying a role value not in the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other check runs. Authorization is then enforced per endpoint; a caller whose role is not on the endpoint's permitted list, or who violates an ownership or scope clause attached to that endpoint, receives `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows: `DiversityAdmin`, `DiversityAnalyst`, `BusinessUnitLead`, `PrimeContact`, `Auditor`.

When `X-User-Role` is `DiversityAdmin`, `DiversityAnalyst`, `BusinessUnitLead`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` on a Certification, `verified_by_user_id` on a Certification, `created_by_user_id` on a ProgramGoal, `reviewed_by_user_id` on a Tier2Report, `auditor_user_id` on an AuditCase, or `submitted_by_user_id` on a Tier2Report — but it does not compare the value to any entity's `id`. Ownership-style checks for these roles are phrased against those recorded fields rather than against entity identity: a `BusinessUnitLead` caller opening, awarding, cancelling, or inviting on a sourcing event must present an `X-User-ID` equal to the `lead_user_id` recorded on the event's `BusinessUnit`, and an `Auditor` recording an outcome must present an `X-User-ID` equal to the `auditor_user_id` on the case.

When `X-User-Role` is `PrimeContact`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `PrimeContact` may only create a tier-2 report whose `prime_supplier_id` equals their `X-User-ID`, and may only edit or submit a report whose `prime_supplier_id` equals their `X-User-ID`.

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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. List results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource has an `id` that is a server-minted UUID with no type prefix. Every resource also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version` that starts at 1 on creation and increments by 1 on every mutation of that resource. All entities in this domain — `BusinessUnit`, `Supplier`, `Certification`, `SpendRecord`, `Tier2Report`, `ProgramGoal`, `Scorecard`, `SourcingEvent`, `BidderInvitation`, `DevelopmentEngagement`, `AuditCase` — carry the full common field set. Every entity except `BusinessUnit` additionally carries a system-managed `status` field holding its current state-machine state; `BusinessUnit` is the lone entity with no lifecycle state.

### 2.5. Money, Precision, and Rounding

All monetary values are integer cents. Fields such as `amount_cents`, `gross_subcontract_cents`, `total_subcontracted_cents`, `total_diverse_tier2_cents`, `total_spend_cents`, `direct_diverse_spend_cents`, `tier2_diverse_spend_cents`, `estimated_value_cents`, `award_amount_cents`, `lifetime_imported_spend_cents`, and `lifetime_voided_spend_cents` are integers; there is no rounding inside the spend-aggregation path because the inputs are already cents. Percentages — `diverse_share_pct` on a tier-2 line, `target_value` for a `PERCENT_OF_SPEND` goal, and `attainment_pct` on a scorecard — are carried to 2 decimal places, and wherever a percentage or a per-line allocation must be rounded, the rule is round-half-up. Two rounding-sensitive pipelines deserve explicit attention. Tier-2 aggregation rounds per line first and then sums; it does not sum first and round once. Attainment percentage rounds half-up at each pinned step in the order written in §3.6, not once at the end. The attainment figure is then capped at 999.99 for display.

### 2.6. Logical Clock

The system maintains a logical clock used for all date-dependent decisions — certification validity windows, expiration sweeps, engagement activation, audit cooling-off. At process startup the clock reads exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time before the first explicit set. A `DiversityAdmin` advances the clock by supplying `to_iso8601` to the clock endpoint. Advancing the clock fires two sweeps at the new date: the certification expiration sweep and the development engagement activation sweep, both described in §3.5 and §3.8 respectively. All date comparisons against the clock use the UTC date of the clock timestamp.

### 2.7. Optimistic Concurrency Control

One write endpoint participates in optimistic concurrency control: creating a `ProgramGoal` against a `BusinessUnit`. The request must carry `expected_business_unit_version` holding the `version` of the parent `BusinessUnit` as the client last observed it. If the business unit's current `version` does not match `expected_business_unit_version` — for example because another writer has since created a goal for the same `(cert_category, fiscal_year)` key, which legitimately supersedes the prior DRAFT under the goal-supersession rule of §3.6 — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the business unit. No other endpoint takes an `expected_..._version` field.

### 2.8. Validation Priority

Where multiple checks could reject the same request, they are evaluated in a fixed priority order so the caller sees a deterministic error. First, header presence and role declaration (§2.1). Second, role permission and any ownership/scope clause on the endpoint. Third, existence of every path identifier and every foreign key in the request body, checked left-to-right along the path and then across body fields. Fourth, whether the target resource is in a state from which the requested transition is defined. Fifth, segregation-of-duties and supplier-eligibility rules. Sixth, uniqueness, overlap, and quota constraints. Seventh, time-window validity at action time. Eighth, money and structural field constraints. This order matters because it decides, for example, whether a caller who fails both an ownership check and an existence check sees `ERR_FORBIDDEN_FOR_ROLE` or `ERR_NOT_FOUND` — they see `ERR_FORBIDDEN_FOR_ROLE`.

### 2.9. Nested Resource Retrieval

When a URL nests one resource under another — a supplier's certifications, a business unit's goals or scorecards, a sourcing event's invitations — path identifiers are validated left-to-right, and each non-terminal identifier must reference an existing resource before the next is resolved. A mismatch or missing resource at any step yields `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Supplier Registration and Lifecycle

Before suppliers can be paid against a business unit, a `DiversityAdmin` creates the unit itself with a display `name`, a short `code` that must be unique across all business units and is immutable after creation, and the `lead_user_id` of the `BusinessUnitLead` who will own its sourcing events. The unit's `inclusion_min_diverse_bidders` — an integer between 0 and 10 inclusive, defaulting to 1 — supplies the default inclusion threshold for events that do not override it, and its two lifetime spend counters start at 0.

A `DiversityAdmin` or `DiversityAnalyst` registers a supplier by providing `legal_name`, `tax_id`, `kind`, and `contact_email`. The `tax_id` must be unique across all suppliers; a duplicate is rejected with `ERR_DUPLICATE_TAX_ID`. The `kind` is one of `DIVERSE`, `PRIME`, or `BOTH`; only `PRIME` and `BOTH` suppliers may file tier-2 reports. A newly registered supplier starts in `REGISTERED` status with `diverse_eligible` set to false and both `risk_score_standard` and `risk_score_conservative` at 0.

The transition from `REGISTERED` to `ACTIVE` is automatic: it fires the moment the supplier's first Certification reaches `VERIFIED`, and it recomputes `diverse_eligible`. A `DiversityAdmin` may suspend an `ACTIVE` supplier, moving it to `SUSPENDED`. Suspension has a deliberate withdrawal cascade: every `BidderInvitation` for that supplier currently in `INVITED` or `BID_SUBMITTED` moves to `WITHDRAWN`, and each of those withdrawals recomputes the owning sourcing event's `diverse_bid_count`. Suspension also recomputes `diverse_eligible`, which drops to false when no `VERIFIED` covering certification remains. Reinstating moves a `SUSPENDED` supplier back to `ACTIVE` and recomputes `diverse_eligible`, but reinstatement is blocked while any audit case for the supplier is `OPEN` — the caller sees `ERR_INVALID_STATE` — and reinstatement does not restore invitations that were withdrawn by the earlier suspension.

### 3.2. Certification Submission, Review, and Verification

A certification captures one diversity credential for one supplier. Submitting one takes `cert_type`, `certifying_body`, `certificate_number`, `valid_from`, and `valid_to`. The `cert_type` is one of `MBE`, `WBE`, `VET`, `SDVET`, `LGBTQBE`, `DOBE`, `SBA8A`, or `SELF_CERT`; for `SELF_CERT` the `certifying_body` is the literal string `SELF`. The `valid_from` is the first covered day inclusive and `valid_to` is the last covered day inclusive; `valid_to` must be on or after `valid_from`, otherwise the submission fails with `ERR_INVALID_REQUEST`. On submission the certification enters `SUBMITTED` and the server stamps `submitted_by_user_id` from the caller's `X-User-ID`. There is one supplier-level guard on submission itself: a `SELF_CERT` submission is rejected with `ERR_AUDIT_COOLING_OFF` when the supplier has a `FAILED` audit outcome recorded within the prior 90 days — measured against `outcome_recorded_at`.

Review is a small state machine. From `SUBMITTED`, a `DiversityAnalyst` or `DiversityAdmin` begins review, moving the certification to `UNDER_REVIEW`. From `UNDER_REVIEW` a reviewer may request more information, moving it to `INFO_REQUESTED` and recording the request in `review_note`; this also recomputes the supplier's risk scores because the CONSERVATIVE variant carries an info-requested term. From `INFO_REQUESTED` the certification can be resubmitted with corrected `certificate_number`, `valid_from`, and `valid_to`, which moves it back to `SUBMITTED` and re-stamps `submitted_by_user_id` with the resubmitting caller. Any review action attempted from a state where that action is not defined — verifying an `EXPIRED`, `REVOKED`, or `REJECTED` certification, for example — is rejected with `ERR_CERT_NOT_REVIEWABLE`, a specialization of the generic state check.

Two terminal decisions come out of `UNDER_REVIEW`. Rejection moves the certification to `REJECTED` and records the reviewer's `reason` in `review_note`. Verification moves it to `VERIFIED`, stamps `verified_by_user_id` with the caller, and is gated by three checks applied together. Segregation of duties requires the caller's `X-User-ID` to differ from `submitted_by_user_id`; a match is `ERR_SOD_VIOLATION`. The window must not already be expired: `valid_to` must be on or after the current logical-clock date, otherwise `ERR_CERT_WINDOW_EXPIRED`. And the supplier must not already hold another certification of the same `cert_type` in `VERIFIED` or `EXPIRED` whose closed validity window overlaps the new one — because the windows are closed, sharing a single boundary day counts as overlap — otherwise `ERR_CERT_WINDOW_OVERLAP`. Both the SoD guard and the eligibility/window guards sit at the same segregation-and-eligibility priority tier (§2.8), while the not-yet-expired check is a business-temporal rule one tier later; the certification must, however, be in `UNDER_REVIEW` first or the state-tier check fires `ERR_CERT_NOT_REVIEWABLE` before any of these.

Verification has three side effects beyond the state change. If the supplier was `REGISTERED`, it becomes `ACTIVE` on its first verified certification. The supplier's `diverse_eligible` is recomputed — it is true exactly when the supplier holds at least one `VERIFIED` certification whose closed `[valid_from, valid_to]` window covers the current clock date. And whenever that recomputation changes the value of `diverse_eligible`, the `diverse_bid_count` of every sourcing event holding an invitation for this supplier is recomputed in turn, so an event's inclusion posture reflects the newly verified (or newly ineligible) supplier.

Once `VERIFIED`, a certification has two ways out. The expiration sweep described in §3.5 moves it to `EXPIRED` when the clock passes `valid_to`. A failed audit — and only a failed audit — moves it to `REVOKED`, with the cascade described in §3.9.

### 3.3. Spend Import and the Business-Unit Ledger

A `DiversityAnalyst` imports spend by supplying `supplier_id`, `business_unit_id`, `amount_cents`, `transaction_date`, `payment_date`, and optionally `po_number`. The `amount_cents` must be greater than 0, otherwise `ERR_INVALID_REQUEST`. The two dates have distinct semantics: `transaction_date` is the accrual-basis date and `payment_date` is the cash-basis date, and which one a scorecard looks at is decided per scorecard at generation time. A new spend record starts in `POSTED`.

Each `BusinessUnit` keeps two monotonic lifetime counters. `lifetime_imported_spend_cents` accumulates `amount_cents` over every spend record ever imported for the unit and is never decremented. `lifetime_voided_spend_cents` accumulates `amount_cents` over every spend record voided for the unit and is likewise never decremented. Together they conserve posted spend: the sum of `amount_cents` over records currently `POSTED` always equals `lifetime_imported_spend_cents` minus `lifetime_voided_spend_cents`. Importing a record adds to the imported counter and bumps the business unit's `version`; voiding a `POSTED` record moves it to `VOIDED`, adds to the voided counter, and bumps the business unit's `version`. Voiding is the compensating action, not a delete. Scorecards that have already been generated are snapshots and are not mutated by a void — the void becomes visible only when a scorecard is recomputed.

### 3.4. Tier-2 Reports from Prime Contractors

A `PrimeContact` files tier-2 subcontracting reports for the prime they represent. Creating a report takes `prime_supplier_id`, `business_unit_id`, `reporting_period`, and `lines`. The `prime_supplier_id` must equal the caller's `X-User-ID` — a `PrimeContact` filing for any other prime receives `ERR_FORBIDDEN_FOR_ROLE` — and the referenced supplier's `kind` must be `PRIME` or `BOTH`, otherwise `ERR_PRIME_ONLY`. The `reporting_period` is a quarter label in the shape `YYYY-Qn` with the quarter digit between 1 and 4; a malformed period is `ERR_INVALID_REQUEST`. Each entry of `lines` carries `diverse_supplier_id`, `gross_subcontract_cents`, and `diverse_share_pct`; the gross must be greater than 0 and the share must be greater than 0 and at most 100.00 with exactly 2 decimal places, otherwise `ERR_INVALID_REQUEST`.

The report's two totals are computed at creation and again whenever the lines are replaced. `total_subcontracted_cents` is the sum of `gross_subcontract_cents` across the lines. `total_diverse_tier2_cents` is the sum of a per-line allocation: for each line, the allocated cents are the gross subcontract cents multiplied by the diverse share percentage divided by 100, rounded half-up to whole cents — and that rounding is applied per line first, before any aggregation, and only then are the per-line amounts summed. Summing first and rounding once at the end yields a different cent total and is not the contract. A new report starts in `DRAFT`.

While a report is `DRAFT` or `RETURNED`, the owning prime may replace its `lines` wholesale via the report-replacement capability; attempting that replacement on a report in any other state is rejected with `ERR_REPORT_NOT_EDITABLE`. Replacing lines recomputes both totals and bumps the report's `version`. Submitting — available from either `DRAFT` or `RETURNED` — requires that the caller own the report and that `lines` be non-empty (an empty submission is `ERR_INVALID_REQUEST`); it moves the report to `SUBMITTED` and stamps `submitted_by_user_id`.

Review is two-pronged. A `DiversityAdmin` or `DiversityAnalyst` may return a `SUBMITTED` report to the prime with a `note`, moving it to `RETURNED` for correction. Approval is reserved for `DiversityAdmin` and applies two eligibility checks to every line: each `diverse_supplier_id` must reference a supplier whose `kind` is `DIVERSE` or `BOTH`, and that supplier must hold a certification in `VERIFIED` or `EXPIRED` status whose closed validity window covers the reporting period's end date — a `REVOKED` certification never qualifies, even if its window would have covered the period. A failure on either check is `ERR_SUPPLIER_NOT_ELIGIBLE`. On approval the report moves from `SUBMITTED` to `APPROVED` and `reviewed_by_user_id` is stamped. Approval also enforces the exactly-one-approved invariant: any other report in `APPROVED` for the same `(prime_supplier_id, reporting_period)` pair automatically transitions to `SUPERSEDED`. Supersession does not mutate any already-generated scorecard; the change becomes visible when a scorecard is recomputed.

### 3.5. The Logical Clock and Its Sweeps

Advancing the logical clock is an admin-only capability that takes `to_iso8601` and fires two sweeps at the new date. The certification expiration sweep examines every certification currently `VERIFIED`: if its `valid_to` is strictly before the new clock date it becomes `EXPIRED`; if `valid_to` equals the new clock date it remains `VERIFIED`, because the validity window is closed and the boundary day is covered. For each certification that expired, the supplier's `diverse_eligible` is recomputed, and any change propagates to the `diverse_bid_count` of sourcing events holding an invitation for that supplier; suppliers whose certifications expired also have their risk scores recomputed to pick up the expired-unrenewed term. The engagement activation sweep then examines every development engagement in `ENROLLED`: any whose `start_date` is on or before the new clock date becomes `ACTIVE`.

### 3.6. Program Goals, Scorecards, and Attainment

A `DiversityAdmin` sets goals for a business unit. Creating a goal takes `fiscal_year`, `cert_category`, `goal_type`, `target_value`, and optionally `include_tier2`; the request must also carry `expected_business_unit_version` per §2.7. The `cert_category` is one of `ALL`, `MBE`, `WBE`, `VET`, `SDVET`, `LGBTQBE`, `DOBE`, `SBA8A`, or `SELF_CERT`; scorecards read only the `ALL`-category goal. The `goal_type` is `PERCENT_OF_SPEND` or `ABSOLUTE_AMOUNT`, and the admissible range of `target_value` depends on it: for `PERCENT_OF_SPEND` the target is a percentage greater than 0 and at most 100.00 with 2 decimals, while for `ABSOLUTE_AMOUNT` it is an integer cents amount greater than 0; an out-of-range value is `ERR_INVALID_REQUEST`. The `include_tier2` flag defaults to true and decides whether approved tier-2 spend counts toward the attainment numerator. A new goal enters `DRAFT` with `created_by_user_id` stamped, and its creation bumps the business unit's `version`. Goal creation also supersedes: any existing `DRAFT` goal for the same `(business_unit_id, cert_category, fiscal_year)` automatically becomes `SUPERSEDED`.

Publishing moves a `DRAFT` goal to `PUBLISHED`. Segregation of duties requires the publisher's `X-User-ID` to differ from `created_by_user_id`; a match is `ERR_SOD_VIOLATION`. Publishing also supersedes: any other `PUBLISHED` goal for the same key automatically becomes `SUPERSEDED`, so at most one published goal exists per `(business_unit_id, cert_category, fiscal_year)` at any time.

A scorecard is a point-in-time snapshot of one business unit for one quarter. Generating one takes `reporting_period` and `attribution_basis`; the basis is `ACCRUAL` or `CASH`, is immutable after generation, and selects which spend-record date the pipeline reads — `transaction_date` under `ACCRUAL`, `payment_date` under `CASH`, so identical underlying records can produce different totals under the two bases. Generation runs the attribution, tier-2 roll-up, and attainment pipeline and leaves the scorecard in `GENERATED`.

Attribution first expands `reporting_period` into its inclusive calendar quarter range — Q1 is January 1 through March 31, Q2 April 1 through June 30, Q3 July 1 through September 30, Q4 October 1 through December 31. The input set is the unit's spend records that are currently `POSTED` and whose basis date falls inside that range; `VOIDED` records are excluded. `total_spend_cents` is the sum of `amount_cents` over the input set. A record in the input set is diverse-attributable exactly when there exists a certification for the record's supplier whose status is `VERIFIED` or `EXPIRED` — never `REVOKED`, and never a pre-verification status — and whose closed validity window covers the record's basis date, boundary days included. `direct_diverse_spend_cents` is the sum of `amount_cents` over attributable records. The `spend_by_category` map accumulates each attributable record's amount under the covering certification's `cert_type`; when more than one certification covers the same record, the amount is attributed to the certification whose `valid_from` is latest, with ties on `valid_from` broken by the certification's `created_at` ascending, and only categories with a positive amount appear in the map.

The tier-2 roll-up then sets `tier2_diverse_spend_cents` to the sum of `total_diverse_tier2_cents` over reports for this business unit and reporting period that are currently `APPROVED`.

Attainment selects the unique goal for this business unit with `cert_category` equal to `ALL`, `fiscal_year` equal to the year of the reporting period, and status `PUBLISHED` — supersession guarantees there is at most one — and records its id in `goal_id`. When no such goal exists, `attainment_pct` is null, `rating` is `NO_GOAL`, and `goal_id` is null. Otherwise the effective diverse spend is `direct_diverse_spend_cents` plus `tier2_diverse_spend_cents` when the goal's `include_tier2` is true, and `direct_diverse_spend_cents` alone when it is false. For a `PERCENT_OF_SPEND` goal, the actual percentage is 0.00 when `total_spend_cents` is 0 and otherwise one hundred times the effective diverse spend divided by `total_spend_cents`, rounded half-up to 2 decimals; `attainment_pct` is then one hundred times that actual percentage divided by the goal's `target_value`, rounded half-up to 2 decimals. For an `ABSOLUTE_AMOUNT` goal, `attainment_pct` is one hundred times the effective diverse spend divided by the goal's `target_value`, rounded half-up to 2 decimals. In both cases the displayed `attainment_pct` is then capped at 999.99. The `rating` bands on the final `attainment_pct` are: at least 110.00 is `EXCEEDS`; at least 100.00 but below 110.00 is `MEETS` — exactly 100.00 is `MEETS`, not `EXCEEDS`; at least 80.00 but below 100.00 is `NEAR`; anything lower is `BELOW`.

A `GENERATED` scorecard can be recomputed from current underlying data; recompute refreshes every computed field under the scorecard's stored `attribution_basis` and bumps the scorecard's `version`. Publishing moves a `GENERATED` scorecard to `PUBLISHED`, locking the snapshot: recompute on a `PUBLISHED` scorecard is rejected with `ERR_SCORECARD_LOCKED`.

### 3.7. Sourcing Events and Diverse-Bid Inclusion

A `BusinessUnitLead` or `DiversityAdmin` creates a sourcing event by supplying `business_unit_id`, `title`, `estimated_value_cents`, and optionally `required_diverse_bidders`. The `estimated_value_cents` must be greater than 0 — it is the award cap. The `required_diverse_bidders` is the minimum number of diverse bidders with submitted bids required to award without a waiver, must lie between 0 and 10 inclusive, and defaults to the business unit's `inclusion_min_diverse_bidders` when omitted. A new event starts in `DRAFT` with `diverse_bid_count` at 0.

Opening moves a `DRAFT` event to `OPEN`. Award and cancel are described below; all three actions, when performed by a `BusinessUnitLead`, require the caller's `X-User-ID` to equal the `lead_user_id` of the event's `BusinessUnit`, otherwise `ERR_FORBIDDEN_FOR_ROLE`. Cancelling is available from `DRAFT` or `OPEN` and moves the event to `CANCELLED`; cancelling an `OPEN` event additionally moves its invitations that are still `INVITED` to `WITHDRAWN`, while invitations already in `BID_SUBMITTED` or `DECLINED` are unchanged.

Invitations attach suppliers to events. Inviting takes `supplier_id` and creates an invitation whose `sourcing_event_id` is the event from the path and whose initial state is `INVITED`. Two guards apply at creation: a supplier currently `SUSPENDED` may not be invited (`ERR_SUPPLIER_NOT_ELIGIBLE`), and an event may hold at most one invitation per supplier — a second invitation for the same `(sourcing_event, supplier)` pair is `ERR_DUPLICATE_INVITATION`. Recording a bid response takes `response` equal to `BID_SUBMITTED` or `DECLINED`; it is defined only for an invitation currently `INVITED` whose owning event is `OPEN` — if the event is not `OPEN` the caller sees `ERR_INVALID_STATE`. A `BID_SUBMITTED` response recomputes the owning event's `diverse_bid_count`; a `DECLINED` response does not.

The `diverse_bid_count` on a sourcing event is a denormalized count of that event's invitations currently in `BID_SUBMITTED` whose supplier is currently `diverse_eligible`. It is recomputed on every invitation mutation and on every supplier-eligibility change that touches an invited supplier, so it reflects both bid flow and the certification-driven eligibility churn described in §3.2 and §3.5.

Awarding an `OPEN` event takes `award_supplier_id`, `award_amount_cents`, and optionally `inclusion_waiver_reason`. Several guards compose here, and their priority follows §2.8. The role and scope tier comes first: a `BusinessUnitLead` caller must match the event's BU `lead_user_id`, and supplying `inclusion_waiver_reason` is restricted to `DiversityAdmin` — a `BusinessUnitLead` supplying one is `ERR_FORBIDDEN_FOR_ROLE` even when they own the BU. At the eligibility tier, the `award_supplier_id` must hold an invitation on this event currently in `BID_SUBMITTED` and that supplier must currently be `ACTIVE`, otherwise `ERR_SUPPLIER_NOT_ELIGIBLE`. At the quota tier, the event's current `diverse_bid_count` must be at least `required_diverse_bidders` — exactly equal passes — unless an `inclusion_waiver_reason` was supplied; an unwaived shortfall is `ERR_INCLUSION_SHORTFALL`. At the fiscal tier, `award_amount_cents` must not exceed `estimated_value_cents`; an overage is `ERR_AWARD_ABOVE_LIMIT`. A successful award moves the event from `OPEN` to `AWARDED` and records `award_supplier_id`, `award_amount_cents`, and `inclusion_waiver_reason` — the last remaining null when the award required no waiver. The invitation cascade then runs: the winning invitation becomes `WON`, every other invitation in `BID_SUBMITTED` becomes `LOST`, every invitation still `INVITED` becomes `NO_RESPONSE`, and invitations in `DECLINED` or `WITHDRAWN` are unchanged.

### 3.8. Development Engagements

A `DiversityAdmin` or `DiversityAnalyst` enrolls a supplier in a development track by supplying `track`, `start_date`, `end_date`, `mentor_name`, and `capacity_score_before`. The `track` is one of `MENTORING`, `CAPABILITY_BUILDING`, or `ACCESS_TO_CAPITAL`. The `capacity_score_before` is a baseline capability score between 0 and 100 inclusive. The engagement window is half-open: `start_date` is the first covered day and `end_date` is exclusive, so `end_date` must be strictly after `start_date` (`ERR_INVALID_REQUEST`). Creation enforces a non-overlap constraint against the supplier's other engagements in `ENROLLED` or `ACTIVE`: the new engagement's half-open window may not overlap such an existing engagement's window, and it may not start less than 30 days after that engagement's `end_date` — a violation is `ERR_ENGAGEMENT_OVERLAP`. A new engagement starts in `ENROLLED` and becomes `ACTIVE` through the clock sweep once its `start_date` is reached (§3.5).

Completing an `ACTIVE` engagement takes `capacity_score_after`, the exit capability score between 0 and 100 inclusive; it moves the engagement to `COMPLETED` and sets `improvement` to `capacity_score_after` minus `capacity_score_before`. Withdrawing is defined from either `ENROLLED` or `ACTIVE` and moves the engagement to `WITHDRAWN`.

### 3.9. Data-Quality Audits and the Revocation Cascade

An `Auditor` opens a data-quality audit by supplying `supplier_id`, `certification_id`, and `reason`. The target certification must have `cert_type` equal to `SELF_CERT` — targeting any other certification type is `ERR_CERT_NOT_SELF_CERT` — and must currently be `VERIFIED`. Segregation of duties forbids the auditor from auditing a certification they personally verified: the caller's `X-User-ID` must differ from the certification's `verified_by_user_id`, otherwise `ERR_SOD_VIOLATION`. At most one audit per certification may be `OPEN` at a time; opening a second is `ERR_AUDIT_ALREADY_OPEN`. A new audit case starts in `OPEN` with `auditor_user_id` stamped from the caller, and its opening recomputes the supplier's risk scores because the CONSERVATIVE variant carries an open-audit term.

Recording an outcome is restricted to the case's owning auditor: the caller's `X-User-ID` must equal `auditor_user_id`, otherwise `ERR_FORBIDDEN_FOR_ROLE`. The submitted `outcome` is `CONFIRMED` or `FAILED`, and in either case `outcome_recorded_at` is stamped with the current logical clock and the case leaves `OPEN` for the matching terminal status.

A `CONFIRMED` outcome recomputes the supplier's risk scores and otherwise leaves the certification and supplier untouched. A `FAILED` outcome fires the revocation cascade. The audited certification moves from `VERIFIED` to `REVOKED` — this is the only producer of `REVOKED` in the system. The revocation in turn suspends the supplier: an `ACTIVE` supplier moves to `SUSPENDED` via the same system-triggered transition as a manual suspension, with the same withdrawal cascade — every invitation in `INVITED` or `BID_SUBMITTED` becomes `WITHDRAWN`, each withdrawal recomputing its event's `diverse_bid_count`. The supplier's `diverse_eligible` is recomputed, and the risk scores are recomputed with the FAILED term now applying. The 90-day self-cert cooling-off clock described in §3.2 runs from `outcome_recorded_at`.

### 3.10. Supplier Risk Scores

Each supplier carries two integer risk scores capped at 100, recomputed whenever an audit outcome is recorded, whenever the expiration sweep expires a certification, whenever a certification moves to `INFO_REQUESTED`, and whenever an audit case is opened. The inputs are four counts over the supplier's audit cases and certifications: the number of audit cases in `FAILED`; the number of audit cases in `OPEN`; the number of certifications in `EXPIRED` for which no other certification of the same `cert_type` is currently `VERIFIED` (the expired-unrenewed count); and the number of certifications in `INFO_REQUESTED`.

`risk_score_standard` weighs confirmed findings only: 40 points per failed audit plus 10 points per expired-unrenewed certification, capped at 100. This is the variant shown to business units on the supplier record. `risk_score_conservative` adds the pending signals the compliance office uses for audit sampling: the same 40 per failed audit and 10 per expired-unrenewed, plus 15 per open audit case and 5 per info-requested certification, again capped at 100. Identical supplier data therefore yields a conservative score greater than or equal to the standard score.

## 4. Endpoint Definitions

All endpoints are mounted under `/api/v1`. Resource-creating endpoints return 201 with the created resource; endpoints that modify an existing resource return 200 with the updated resource; list and get endpoints return 200. Error responses use the envelope in §2.2 with the error IDs catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/v1/business-units | Create a business unit | DiversityAdmin |
| GET | /api/v1/business-units/{id} | Get a business unit, including computed lifetime spend counters | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| POST | /api/v1/suppliers | Register a supplier (diverse, prime, or both) | DiversityAdmin, DiversityAnalyst |
| GET | /api/v1/suppliers/{id} | Get a supplier, including `diverse_eligible` and both risk score variants | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor, PrimeContact |
| POST | /api/v1/suppliers/{id}/suspend | Suspend a supplier; withdraws its INVITED/BID_SUBMITTED invitations and recomputes event `diverse_bid_count` | DiversityAdmin |
| POST | /api/v1/suppliers/{id}/reinstate | Reinstate a suspended supplier (blocked while an audit case is OPEN) | DiversityAdmin |
| POST | /api/v1/suppliers/{id}/certifications | Submit a certification for review | DiversityAdmin, DiversityAnalyst |
| GET | /api/v1/suppliers/{id}/certifications | List certifications of a supplier | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor, PrimeContact |
| POST | /api/v1/certifications/{id}/begin-review | Move certification SUBMITTED to UNDER_REVIEW | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/certifications/{id}/request-info | Move certification UNDER_REVIEW to INFO_REQUESTED with a note | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/certifications/{id}/resubmit | Move certification INFO_REQUESTED to SUBMITTED with corrected fields | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/certifications/{id}/verify | Verify a certification (SoD: caller is not the submitter) | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/certifications/{id}/reject | Reject a certification under review (SoD: caller is not the submitter) | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/spend-records | Import a spend record | DiversityAnalyst |
| GET | /api/v1/spend-records | List spend records with filters and pagination | DiversityAdmin, DiversityAnalyst, Auditor |
| GET | /api/v1/spend-records/{id} | Get a spend record | DiversityAdmin, DiversityAnalyst, Auditor |
| POST | /api/v1/spend-records/{id}/void | Void a posted spend record | DiversityAnalyst |
| POST | /api/v1/tier-2-reports | Create a DRAFT tier-2 report | PrimeContact |
| GET | /api/v1/tier-2-reports | List tier-2 reports with filters and pagination | DiversityAdmin, DiversityAnalyst, Auditor, PrimeContact |
| GET | /api/v1/tier-2-reports/{id} | Get a tier-2 report | DiversityAdmin, DiversityAnalyst, Auditor, PrimeContact |
| PUT | /api/v1/tier-2-reports/{id} | Replace lines while DRAFT or RETURNED | PrimeContact |
| POST | /api/v1/tier-2-reports/{id}/submit | Submit a DRAFT or RETURNED report (owner only) | PrimeContact |
| POST | /api/v1/tier-2-reports/{id}/approve | Approve a SUBMITTED report | DiversityAdmin |
| POST | /api/v1/tier-2-reports/{id}/return | Return a SUBMITTED report for correction | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/business-units/{id}/goals | Create a DRAFT goal for a business unit | DiversityAdmin |
| GET | /api/v1/business-units/{id}/goals | List goals of a business unit | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| POST | /api/v1/goals/{id}/publish | Publish a DRAFT goal (SoD: caller is not the creator) | DiversityAdmin |
| POST | /api/v1/business-units/{id}/scorecards | Generate a scorecard snapshot for a quarter | DiversityAdmin, DiversityAnalyst |
| GET | /api/v1/business-units/{id}/scorecards | List scorecards of a business unit | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| GET | /api/v1/scorecards/{id} | Get a scorecard | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| GET | /api/v1/scorecards | List scorecards across business units | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| POST | /api/v1/scorecards/{id}/recompute | Recompute a GENERATED scorecard | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/scorecards/{id}/publish | Publish (lock) a GENERATED scorecard | DiversityAdmin |
| POST | /api/v1/sourcing-events | Create a sourcing event | BusinessUnitLead, DiversityAdmin |
| GET | /api/v1/sourcing-events | List sourcing events with filters and pagination | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| GET | /api/v1/sourcing-events/{id} | Get a sourcing event | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| POST | /api/v1/sourcing-events/{id}/open | Open a DRAFT event for bidding | BusinessUnitLead, DiversityAdmin |
| POST | /api/v1/sourcing-events/{id}/award | Award an OPEN event | BusinessUnitLead, DiversityAdmin |
| POST | /api/v1/sourcing-events/{id}/cancel | Cancel a DRAFT or OPEN event | BusinessUnitLead, DiversityAdmin |
| POST | /api/v1/sourcing-events/{id}/invitations | Invite a supplier to an event | BusinessUnitLead, DiversityAdmin |
| GET | /api/v1/sourcing-events/{id}/invitations | List invitations of a sourcing event | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| GET | /api/v1/suppliers/{id}/invitations | List invitations received by a supplier | DiversityAdmin, DiversityAnalyst, BusinessUnitLead, Auditor |
| POST | /api/v1/invitations/{id}/respond | Record a bid response for an INVITED invitation on an OPEN event | BusinessUnitLead, DiversityAdmin |
| POST | /api/v1/suppliers/{id}/development-engagements | Enroll a supplier in a development track | DiversityAdmin, DiversityAnalyst |
| GET | /api/v1/suppliers/{id}/development-engagements | List development engagements of a supplier | DiversityAdmin, DiversityAnalyst, Auditor |
| POST | /api/v1/development-engagements/{id}/complete | Complete an ACTIVE engagement with an exit capacity score | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/development-engagements/{id}/withdraw | Withdraw an ENROLLED or ACTIVE engagement | DiversityAdmin, DiversityAnalyst |
| POST | /api/v1/audit-cases | Open a data-quality audit on a VERIFIED SELF_CERT certification | Auditor |
| GET | /api/v1/audit-cases | List audit cases with filters and pagination | DiversityAdmin, DiversityAnalyst, Auditor |
| GET | /api/v1/audit-cases/{id} | Get an audit case | DiversityAdmin, DiversityAnalyst, Auditor |
| POST | /api/v1/audit-cases/{id}/record-outcome | Record CONFIRMED or FAILED for an OPEN audit (owning auditor only) | Auditor |
| POST | /api/v1/_clock/set_current_utc | Set the logical clock; fires the expiration and activation sweeps | DiversityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CERT_NOT_REVIEWABLE | 409 |
| ERR_CERT_WINDOW_EXPIRED | 409 |
| ERR_CERT_WINDOW_OVERLAP | 409 |
| ERR_CERT_NOT_SELF_CERT | 409 |
| ERR_AUDIT_ALREADY_OPEN | 409 |
| ERR_AUDIT_COOLING_OFF | 409 |
| ERR_SOD_VIOLATION | 409 |
| ERR_SUPPLIER_NOT_ELIGIBLE | 409 |
| ERR_PRIME_ONLY | 409 |
| ERR_INCLUSION_SHORTFALL | 409 |
| ERR_AWARD_ABOVE_LIMIT | 409 |
| ERR_SCORECARD_LOCKED | 409 |
| ERR_REPORT_NOT_EDITABLE | 409 |
| ERR_DUPLICATE_INVITATION | 409 |
| ERR_DUPLICATE_TAX_ID | 409 |
| ERR_ENGAGEMENT_OVERLAP | 409 |
