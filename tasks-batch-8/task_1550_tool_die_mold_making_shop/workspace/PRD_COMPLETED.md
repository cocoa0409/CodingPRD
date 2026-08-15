# Tool Die Mold Shop API — Product Requirements Document

## 1. Introduction

A Midwest tool-and-die and mold-making shop lives and dies by two things: how accurately it prices complex tooling up front, and how disciplined it stays about money while a build is on the floor. The shop designs and builds production tooling across five die classes — from `CLASS_101`, rated for a million shots or more of production duty, down to `CLASS_105` prototype tooling — spanning progressive dies, transfer dies, injection molds, blow molds, and compression molds. Every job moves through a familiar arc: a customer submits part data, the shop's engineers review and release a design, an estimator prices the tool against the design's class, cavitation, complexity, and requested lead time, the customer accepts a quote, and the build proceeds through six canonical milestones from design completion to delivery acceptance, each carrying a contractual billing percentage. Tryout presses prove the tool through T1 sampling until quality signs the buyoff; only then does the tool ship — and even then the shop retains a tooler's lien on ownership until the contract is effectively paid in full.

This document specifies the API that runs that shop end to end. It governs quote price construction with lead-time compression surcharges, expedited multipliers, and quote-kind contingencies; progress billing with a payment waterfall and strict segregation of duties between the person who issues an invoice and the person who records payment against it; engineering change orders that re-baseline the contract value and replan milestone billing mid-flight; tryout and buyoff loops with rework-authorization controls; warranty adjudication with two proration variants keyed to shot life; spare-insert inventory with reorder flagging; and press and machine scheduling under two deliberately different overlap regimes. All time-dependent behavior — invoice aging and credit suspension, quote expiry, reservation windows, warranty expiration — is driven by a single shop-wide logical clock rather than the wall clock, so that every rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, declaring the caller's role. If either header is missing, or the role value is not one of the declared roles, the request fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). If the caller's role is not among the roles permitted for the endpoint, the request fails with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles are `ShopAdmin`, `Estimator`, `ToolingEngineer`, `ProjectManager`, `QualityManager`, `FinanceAdmin`, and `Customer`. The endpoint tables additionally use `Any`, which is not an account type: it denotes that every authenticated role may call read endpoints.

Role identity semantics differ by role, and the difference is load-bearing for ownership checks:

- When `X-User-Role` is `ShopAdmin`, `Estimator`, `ToolingEngineer`, `ProjectManager`, `QualityManager`, or `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `issued_by_user_id` on a progress invoice or `recorded_by_user_id` on a payment — but it never compares that value to any entity's `id`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting customer record; ownership checks on any resource that references a customer compare the resource's `customer_id` foreign key to `X-User-ID`. A customer acting on a resource owned by a different customer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This applies to design creation and submission, quote responses, engineering-change filing and customer decisions, the buyoff-signature milestone, shot reports, and warranty claims.
- `Any` behaves as an opaque identity for read access; no ownership comparison applies to reads.

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

### 2.3. Pagination and List Ordering

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. A `limit` that is not an integer, is below 1, or is above 100, or an `offset` that is not an integer or is negative, is a shape failure under §2.7 tier 3 (`ERR_INVALID_REQUEST`, HTTP 400). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Unless a resource states otherwise, list endpoints sort by `created_at` ascending; ties on `created_at` are broken by server-internal creation order (the order in which resources were persisted). Four resources override the default ordering: build milestones are sorted by `build_job_id` ascending and then `seq` ascending; shot reports are sorted by `report_period_end` ascending (with creation-order tiebreak); press reservations and machine reservations are each sorted by `start_time` ascending (with creation-order tiebreak). All list filters are exact-equality matches against the named field.

### 2.4. The Logical Clock

The shop runs on a single logical clock. Every rule in this document that says "now" — reservation start validity, tryout window membership, quote expiry, invoice due dates and aging, warranty expiry, shot-report period ends — reads this clock, never the real wall clock. Before any operator sets it, the logical clock starts at exactly 2026-08-01T00:00:00Z.

A `ShopAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. The clock must never move backward: a `to_iso8601` earlier than the current logical time is rejected. The capability responds with the clock's new value as `current_utc`. Every clock advance triggers the customer credit-aging suspension sweep described in §2.8. All datetimes in the API are ISO 8601 UTC with three fractional digits, and datetime comparisons resolve to the second.

### 2.5. Resource Identity, Versioning, and Optimistic Concurrency

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and a `version` integer that starts at 1 at creation and increments on every mutation of the resource. Two resources are exceptions: payments and shot reports carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

Resources are addressed by path identifiers: `customerId`, `designId`, `quoteId`, `jobId`, `milestoneId`, `invoiceId`, `paymentId`, `sampleId`, `ecoId`, `raId`, `toolId`, `reportId`, `claimId`, `insertId`, and `resId`. When a path carries more than one identifier, existence is validated left to right along the path; only then are body-level foreign-key references (`customer_id`, `tool_design_id`, `quote_id`, `build_job_id`, `press_reservation_id`, `tool_asset_id`, `rework_authorization_id`) checked.

Three write operations are guarded by optimistic concurrency control against their parent entity:

- Creating a quote requires a non-optional `expected_tool_design_version` carrying the client's last observed `version` of the referenced tool design. If the design's version has advanced since the client read it — a revision was released, or another quote was created against the design, bumping its `quoted_count` and `version` — the create is rejected with `ERR_STALE_TOOL_DESIGN_VERSION` (HTTP 412), so the shop never prices a stale design baseline.
- Filing an engineering change requires a non-optional `expected_build_job_version` carrying the client's last observed `version` of the build job. A mismatch with the job's current `version` is rejected with `ERR_STALE_BUILD_JOB_VERSION` (HTTP 412), preventing an assessment against a contract baseline the client has not observed.
- Recording a payment against a job likewise requires `expected_build_job_version`; a mismatch is rejected with `ERR_STALE_BUILD_JOB_VERSION` (HTTP 412), so the waterfall never allocates against stale balances.

Endpoints not listed here take no version field. Version bumps are themselves part of the contract: submitting or reviewing a design increments the design's `version`; creating a quote increments the design's `version` (through `quoted_count`); advancing, holding, resuming, filing an engineering change against, or recording a payment against a job each increments the job's `version`; and the credit-aging sweep increments the customer's `version` when it suspends one. Cascade side effects bump the version of every entity they mutate: the supersede cascade of §3.2 increments the prior `RELEASED` design's `version` when moving it to `SUPERSEDED`; the quote-issuance supersede cascade of §3.3 increments every other `ISSUED` quote it supersedes; the milestone and tool transitions triggered by tryout, buyoff, payment, ECO-approval, shipping, and delivery flows each increment the affected milestone's, tool's, or job's `version`. Restoring a suspended customer to `ACTIVE` does not increment the customer's `version` (it updates only `updated_at`).

### 2.6. Money, Precision, and Rounding Discipline

All monetary values are integer cents. Rounding is round-half-up and occurs only at pinned steps, never mid-formula except where this document says so: the quote subtotal and the quote total (§3.3); each milestone's planned amount, rounded per line before the remainder is absorbed (§3.4); the labor, material, and schedule-penalty lines of an engineering-change assessment (§3.7); and the final step of a warranty credit (§3.9). The payment waterfall is exact integer arithmetic with no rounding. Reservation durations are expressed in hours to a precision of one hundredth of an hour, and capacity comparisons are evaluated at the exact boundary.

### 2.7. Validation Order of Precedence

When several checks could reject the same request, the server evaluates them in a fixed order, and a failure in an earlier tier masks every later tier. The twelve tiers, in order:

1. **Header validity.** `X-User-ID` and `X-User-Role` are present and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401).
2. **Role authorization.** The caller's role is permitted on the endpoint — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Request shape.** Required fields are present, unknown payload keys are rejected, enum values are in-domain (`die_class`, `tool_type`, `quote_kind`, `decision`, `target_state`, `press_id`, `machine_id`, `warranty_terms`), and declared ranges hold: `cavity_count` between 1 and 64 inclusive, `design_complexity_score` between 1 and 20 inclusive, `requested_lead_weeks` at least 1, `affects_from_milestone_seq` between 1 and 6 inclusive, monetary and quantity amounts at their declared minimums of 0 or 1. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400), with out-of-domain enum values surfaced as `ERR_INVALID_ENUM_VALUE` (HTTP 400). An empty `defect_codes` array on a `REJECTED` buyoff decision and an empty `denial_reason` on a `DENY` claim decision are shape failures caught here.
4. **Existence.** Path identifiers are validated left to right, then body foreign keys; each missing resource surfaces its own 404 — `ERR_CUSTOMER_NOT_FOUND`, `ERR_TOOL_DESIGN_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_BUILD_JOB_NOT_FOUND`, `ERR_BUILD_MILESTONE_NOT_FOUND`, `ERR_PROGRESS_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_TRYOUT_SAMPLE_NOT_FOUND`, `ERR_ENGINEERING_CHANGE_NOT_FOUND`, `ERR_REWORK_AUTHORIZATION_NOT_FOUND`, `ERR_TOOL_ASSET_NOT_FOUND`, `ERR_SHOT_REPORT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_SPARE_INSERT_NOT_FOUND`, `ERR_PRESS_RESERVATION_NOT_FOUND`, or `ERR_MACHINE_RESERVATION_NOT_FOUND`.
5. **Ownership.** A `Customer` caller may act only on resources whose owning `customer_id` equals `X-User-ID` — otherwise `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
6. **Optimistic concurrency.** `expected_tool_design_version` or `expected_build_job_version` must equal the parent's current `version` — otherwise `ERR_STALE_TOOL_DESIGN_VERSION` or `ERR_STALE_BUILD_JOB_VERSION` (HTTP 412).
7. **State preconditions.** The target resource must be in the state machine's required from-state — otherwise `ERR_INVALID_STATE`, `ERR_JOB_ON_HOLD`, or `ERR_JOB_PHASE_MISMATCH` (HTTP 409).
8. **Segregation of duties.** When recording a payment, the simulated allocation is checked first: if any invoice that would receive money was issued by the same `X-User-ID` now recording the payment, the request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This tier deliberately runs before the overpayment check in tier 12.
9. **Temporal rules.** Reservation windows must have `end_time` strictly after `start_time` with `start_time` not in the past, tryout submits must fall inside the press window, quote responses must arrive before expiry, warranty claims must be filed before warranty expiry, and shot-report periods must not end in the future — surfacing `ERR_INVALID_TIME_WINDOW` (HTTP 422), `ERR_OUTSIDE_RESERVATION_WINDOW`, `ERR_QUOTE_EXPIRED`, or `ERR_WARRANTY_TIME_EXPIRED`. At warranty-claim filing the time-expiry check is evaluated before the shot-limit check and wins when both would fail.
10. **Resource and graph constraints.** Press and machine overlap (`ERR_PRESS_DOUBLE_BOOKED`, `ERR_MACHINE_WINDOW_CONFLICT`), machine weekly capacity (`ERR_MACHINE_CAPACITY_EXCEEDED`), milestone ordering and actor rules (`ERR_MILESTONE_SEQUENCE_BLOCKED`, `ERR_MILESTONE_ACTOR_MISMATCH`), the one-`RELEASED`-design rule (`ERR_DUPLICATE_RELEASED_DESIGN`), one job per quote (`ERR_JOB_ALREADY_EXISTS`), monotonic shot periods (`ERR_NON_MONOTONIC_SHOT_PERIOD`), the shot-reversal guard (`ERR_SHOT_REVERSAL_BLOCKED`), stock sufficiency (`ERR_INSUFFICIENT_STOCK`), rework authorization at round three and beyond (`ERR_REWORK_REQUIRES_AUTHORIZATION`), rework cost overrun (`ERR_REWORK_COST_OVERRUN`), and lead-time feasibility (`ERR_LEAD_TIME_INFEASIBLE`).
11. **Cross-entity state gates.** Customer must be `ACTIVE` for quote creation and acceptance (`ERR_CUSTOMER_SUSPENDED`), a `FIRM` quote requires a `RELEASED` design (`ERR_DESIGN_NOT_RELEASED`), production-gated operations require the tool in production (`ERR_TOOL_NOT_IN_PRODUCTION`), and job creation requires an accepted quote (`ERR_QUOTE_NOT_ACCEPTED`).
12. **Money gates, last.** Overpayment (`ERR_OVERPAYMENT`, HTTP 422), the retention-lien ship gate (`ERR_RETENTION_LIEN_BLOCK`, HTTP 402), and the customer credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402) are evaluated only after everything above has passed.

### 2.8. Credit Standing, Suspension, and the Tooler's Retention Lien

Two shop-wide exposure rules cut across the workflows and are stated here once.

**Customer credit.** Every customer carries `credit_limit_cents`, a ceiling on open exposure where 0 means unlimited. The customer's `outstanding_balance_cents` is the sum of `balance_due_cents` over every progress invoice of every job belonging to that customer whose status is `ISSUED` or `PARTIALLY_PAID`. Invoices are issued on net-30 terms: an invoice's `due_date` is thirty days after issuance. A grace period of ten further days applies: when the logical clock passes an open invoice's `due_date` by more than ten days, the customer flips from `ACTIVE` to `SUSPENDED` (incrementing the customer's `version`); when no such invoice remains, the customer is restored to `ACTIVE` (without a version increment — only `updated_at` advances). The evaluation runs on every logical-clock advance and after every recorded payment.

**The tooler's lien.** Until a tool is fully paid, the shop retains ownership of it. Shipping is gated by a lien threshold — the floor of fifteen hundredths of the job's `contract_value_cents` — and ownership passes only when the job is paid to the exact cent and the tool has reached production. Both rules are specified operationally in §3.8.

### 2.9. Shop-Floor Scheduling: Press Windows and Machine Capacity

The shop floor exposes three tryout presses — `PRESS_200T`, `PRESS_500T`, and `PRESS_800T` — and four machines — `CNC_1`, `CNC_2`, `EDM_1`, and `GRIND_1`. The two reservation kinds deliberately use different overlap semantics.

A **press window** occupies the half-open interval from `start_time` up to but not including `end_time`. A new window conflicts with an existing `RESERVED` window on the same press unless the new window ends at or before the existing window's start, or starts at or after the existing window's end; a conflicting booking is rejected with `ERR_PRESS_DOUBLE_BOOKED`. Back-to-back adjacency is therefore allowed: a window starting exactly when another ends does not conflict. Every window requires `end_time` strictly after `start_time` and `start_time` at or after the current logical time, failing with `ERR_INVALID_TIME_WINDOW` otherwise.

A **machine block** occupies a buffer-extended interval: the block itself plus a four-hour cool-down after its `end_time`. A new block conflicts with an existing `RESERVED` block on the same machine unless the new block starts at or after the existing block's end plus four hours, or the existing block starts at or after the new block's end plus four hours; conflicts are rejected with `ERR_MACHINE_WINDOW_CONFLICT`. Consequently a block starting exactly when another block ends still conflicts — it falls inside the cool-down — while a block starting exactly four hours after that end is allowed. On top of the pairwise check, each machine has a weekly capacity of 45.0 hours: for the ISO week (the Monday 00:00 UTC bucket) containing the new block's `start_time`, the sum of `duration_hours` over that machine's `RESERVED` blocks starting in that week plus the new block's `duration_hours` must not exceed 45.0; the boundary is inclusive, so exactly 45.0 hours is allowed, and any excess is rejected with `ERR_MACHINE_CAPACITY_EXCEEDED`. `duration_hours` is the block's length in hours, computed to a precision of one hundredth of an hour.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Credit Standing

A `ShopAdmin` onboards each customer with a `company_name`, a `contact_email`, and an optional `credit_limit_cents`. The credit limit defaults to 0 — meaning unlimited — and may not be negative. New customers start in `ACTIVE` status with an `outstanding_balance_cents` of zero. The customer list can be filtered by `status`.

`outstanding_balance_cents` is never written directly: it is always the sum of `balance_due_cents` across the customer's open invoices (`ISSUED` or `PARTIALLY_PAID`), as defined in §2.8. When the credit-aging sweep — or a payment — finds any open invoice more than ten days past its `due_date`, the customer becomes `SUSPENDED`; while suspended, the shop will not create quotes for that customer and the customer cannot accept one, both attempts failing with `ERR_CUSTOMER_SUSPENDED`. Once no invoice remains past the grace period, the customer returns to `ACTIVE`. Suspension and restoration are system actions; no endpoint flips a customer's status directly.

### 3.2. Tool Design Submission, Engineering Review, and Revision Chains

A customer initiates the lifecycle by submitting part data for a new tool design: a payload carrying `customer_id`, `part_number`, `tool_type`, `die_class`, `cavity_count`, and `design_complexity_score`. `tool_type` is one of `PROGRESSIVE_DIE`, `TRANSFER_DIE`, `INJECTION_MOLD`, `BLOW_MOLD`, or `COMPRESSION_MOLD`; `die_class` is one of `CLASS_101` through `CLASS_105`. Cavitation is bounded — `cavity_count` from 1 to 64 — and engineering complexity (slides, lifters, tolerance stack-ups) is scored on `design_complexity_score` from 1 to 20. The `customer_id` must equal the caller's `X-User-ID`, failing with `ERR_NOT_RESOURCE_OWNER` otherwise. A new design starts in `DRAFT` with `revision_number` 1, a null `supersedes_design_id`, and a `quoted_count` of zero.

Submitting the design — a `DRAFT` to `SUBMITTED` move — is the owning customer's action and increments the design's `version`. Review belongs to a `ToolingEngineer`, who passes a `decision` and may attach an optional `review_note`. A `REJECTED` decision loops the design back from `SUBMITTED` to `DRAFT` so the customer can refine and resubmit. A `RELEASED` decision is guarded: no other design for the same `customer_id` and `part_number` may already be `RELEASED`, unless that other design is the head of this design's supersedes chain — a violation is rejected with `ERR_DUPLICATE_RELEASED_DESIGN`. When a release succeeds, the design named by this design's `supersedes_design_id`, if still `RELEASED`, cascades from `RELEASED` to `SUPERSEDED`, so at most one live revision of a part exists at any time. `SUPERSEDED` is terminal. Either review outcome increments the design's `version`.

A `ToolingEngineer` may also spin off the next revision of a `RELEASED` or `SUBMITTED` design. The revision is a brand-new design in `DRAFT`: its `revision_number` is the source design's plus one, its `supersedes_design_id` points back at the source, and it inherits `part_number`, `customer_id`, and any of `cavity_count`, `design_complexity_score`, `die_class`, and `tool_type` that the caller did not override in the request. The design list supports filtering by `customer_id`, `status`, and `part_number`.

### 3.3. Quoting and Price Construction

An `Estimator` creates a quote against any design — a design of any lifecycle status may be quoted; the release gate applies only at issuance. The create payload carries `customer_id`, `tool_design_id`, `quote_kind` (`BUDGETARY` or `FIRM`), `requested_lead_weeks`, an optional `expedited` flag defaulting to false, an optional `warranty_terms` (defaulting to `LINEAR_PRORATION`; `DECLINING_BALANCE` is the alternative, and the choice is later copied onto the tool), and the OCC field `expected_tool_design_version` described in §2.5. Body-level foreign-key existence is checked with `customer_id` first, then `tool_design_id` — a missing customer surfaces `ERR_CUSTOMER_NOT_FOUND` even when the design id is also unknown. Two gates apply at creation. First, lead-time feasibility: `requested_lead_weeks` must be at least the class minimum — 12 weeks for `CLASS_101`, 10 for `CLASS_102`, 8 for `CLASS_103`, 6 for `CLASS_104`, 3 for `CLASS_105` — with a request exactly at the minimum allowed and anything shorter rejected with `ERR_LEAD_TIME_INFEASIBLE`. Second, the customer must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`). Creating a quote also feeds back into the design: the design's `quoted_count` increases by one and its `version` increments — which is precisely what invalidates other estimators' stale `expected_tool_design_version` values.

The quote price is computed once, at creation, and frozen on the quote thereafter. The computation is exact-decimal arithmetic with round-half-up to integer cents at exactly two pinned steps:

1. `base_price_cents` is the class base plus cavitation plus complexity: a class base of 12,000,000 cents for `CLASS_101`, 9,000,000 for `CLASS_102`, 6,500,000 for `CLASS_103`, 4,000,000 for `CLASS_104`, or 1,800,000 for `CLASS_105`; plus `cavity_count` multiplied by the per-cavity rate of 800,000, 650,000, 500,000, 350,000, or 200,000 cents for classes 101 through 105 respectively; plus `design_complexity_score` multiplied by 150,000 cents per point. All three inputs are read from the referenced design.
2. Lead compression drives `surcharge_pct`. The compression weeks are the class's standard lead time — 20, 16, 12, 10, or 6 weeks for classes 101 through 105 — minus `requested_lead_weeks`, floored at zero. The surcharge fraction is four hundredths per compression week, capped at forty hundredths, so `surcharge_pct` always lies between 0.00 and 0.40 inclusive.
3. The pre-contingency subtotal is `base_price_cents` multiplied by one plus the surcharge fraction; if `expedited` is set, the result is then multiplied by 1.10. The outcome is rounded half-up to integer cents and frozen as `subtotal_cents` — the first pinned rounding step.
4. `contingency_pct` is 0.15 for a `BUDGETARY` quote and 0.05 for a `FIRM` quote.
5. `total_price_cents` is `subtotal_cents` multiplied by one plus `contingency_pct`, rounded half-up to integer cents — the second and final rounding step.

Issuing a `DRAFT` quote is an `Estimator` action that moves it to `ISSUED`. A `FIRM` quote may only be issued against a `RELEASED` design — otherwise `ERR_DESIGN_NOT_RELEASED`; a `BUDGETARY` quote may be issued while the design is `SUBMITTED` or `RELEASED`. Issuance stamps `issued_at` from the logical clock and computes `valid_until` as fourteen days after issuance for `BUDGETARY` quotes and thirty days for `FIRM` quotes (both remain null while the quote is in `DRAFT`). Issuance also supersedes the quote's predecessors: every other quote for the same `tool_design_id` still sitting in `ISSUED` transitions to `SUPERSEDED`.

The owning customer answers an issued quote with a `decision`. Ownership is checked first (`ERR_NOT_RESOURCE_OWNER`). If the logical clock has passed `valid_until`, the quote lazily transitions from `ISSUED` to `EXPIRED` and the response call itself fails with `ERR_QUOTE_EXPIRED` — this applies equally to accepts and declines. An `ACCEPTED` decision then runs two gates in order: the customer must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`), and the credit gate — `credit_limit_cents` of 0 means unlimited; otherwise `outstanding_balance_cents` plus this quote's `total_price_cents` must be less than or equal to `credit_limit_cents`, the boundary inclusive, failing with `ERR_CREDIT_LIMIT_EXCEEDED`. A `DECLINED` decision needs only the ownership and expiry checks. `ACCEPTED`, `DECLINED`, `EXPIRED`, and `SUPERSEDED` are all terminal for a quote. The quote list supports filtering by `customer_id`, `tool_design_id`, and `status`.

### 3.4. Booking the Build Job and Scheduling Capacity

Once a quote is `ACCEPTED`, a `ProjectManager` books the build by supplying the `quote_id`. The quote must be `ACCEPTED` (`ERR_QUOTE_NOT_ACCEPTED`), and at most one build job may exist per quote — a second attempt fails with `ERR_JOB_ALREADY_EXISTS`. The new job starts in `BOOKED` with `hold_return_state` null. It denormalizes `customer_id` and `tool_design_id` from the quote, copies `die_class` from the design (immutable thereafter), and snapshots `contract_value_cents` from the quote's `total_price_cents`; that baseline is later re-baselined by approved engineering changes (§3.7).

Booking mints two things. First, the six canonical milestones, in `seq` order 1 through 6 with `code` values `DESIGN_COMPLETE`, `MATERIAL_STAGED`, `MACHINING_COMPLETE`, `T1_TRYOUT_DONE`, `BUYOFF_SIGNED`, and `DELIVERY_ACCEPTED`, carrying `billing_pct` values of 20, 25, 25, 15, 10, and 5 percent respectively. Each milestone's `planned_amount_cents` is planned by the pinned rounding order of §3.5. Second, exactly one tool asset per job: a server-minted `serial_number` of the form TLT-<n>, `physical_status` `IN_BUILD`, `ownership_status` `SHOP_RETAINED`, `die_class` copied from the job, `warranty_terms` copied from the quote, `warranty_shot_limit` set by die class — 1,000,000 shots for `CLASS_101`, 500,000 for `CLASS_102`, 250,000 for `CLASS_103`, 100,000 for `CLASS_104`, 10,000 for `CLASS_105` — `contract_snapshot_cents` equal to the contract value at creation, and `tryout_shots`, `reported_shots`, and `lifetime_shots` all zero with `warranty_expires_at` still null.

Several job figures are always derived, never stored by callers: `billed_cents` is the sum of `amount_cents` over the job's invoices not in `VOID`; `paid_cents` is the sum of payment allocation `applied_cents` over all payments on the job; `credit_balance_cents` is the sum over milestones of the positive part of each milestone's `paid_cents` minus its `planned_amount_cents`; `net_paid_cents` is `paid_cents` minus `credit_balance_cents`; `outstanding_cents` is `contract_value_cents` minus `net_paid_cents`; and `open_eco_count` counts the job's engineering changes sitting in `SUBMITTED`, `IMPACT_ASSESSED`, or `APPROVED`.

Capacity is scheduled before and during the build. Machine blocks are booked against a job with `build_job_id`, `machine_id`, `start_time`, and `end_time`; press windows likewise with `build_job_id`, `press_id`, `start_time`, and `end_time`. The overlap, buffer, weekly-capacity, and window-validity rules of §2.9 apply at booking. Either reservation kind can later be cancelled, moving `RESERVED` to `CANCELLED`; a press window's cancellation is refused with `ERR_INVALID_STATE` while any tryout sample references it in `SCHEDULED` or `SUBMITTED` status. Reservation lists filter by `build_job_id`, `press_id` or `machine_id`, and `status`.

Moving the job forward is a `ProjectManager` action with an explicit `target_state`, and only two advances are legal: `BOOKED` to `IN_BUILD`, which requires at least one `RESERVED` machine reservation on the job (`ERR_NO_CAPACITY_RESERVED`), and `BUYOFF_PASSED` to `READY_TO_SHIP`, which requires milestones with `seq` 1 through 5 all in `EARNED`, `INVOICED`, or `PAID` (`ERR_MILESTONE_SEQUENCE_BLOCKED`). Any other advance target is rejected with `ERR_INVALID_STATE` (an out-of-domain value is a shape failure under §2.7 tier 3). Each successful advance increments the job's `version`. The remaining forward moves are system-driven: the job leaves `IN_BUILD` for `TRYOUT_PHASE` when the job's first tryout sample is created, leaves `READY_TO_SHIP` for `SHIPPED` when the tool ships, and leaves `SHIPPED` for `CLOSED` — the terminal state — when ownership of the tool transfers.

A job in `BOOKED`, `IN_BUILD`, `TRYOUT_PHASE`, `BUYOFF_PASSED`, or `READY_TO_SHIP` may be put on hold. Holding captures the current state into `hold_return_state` and moves the job to `ON_HOLD`; resuming returns the job to `hold_return_state` and clears that field to null. Both actions increment the job's `version`. While a job is `ON_HOLD`, operational actions on it — completing milestones, filing engineering changes, initiating sample rework — are rejected with `ERR_JOB_ON_HOLD`. Jobs can be listed with filters on `customer_id` and `status`.

### 3.5. Milestones, Progress Billing, and the Payment Waterfall

Milestones are earned in strict sequence. Completing a milestone — moving it from `PENDING` to `EARNED`, or from `REOPENED` back to `EARNED` after rework — is a `ProjectManager` action for sequences 1 through 4 and 6, and the owning customer's action for sequence 5, the `BUYOFF_SIGNED` signature. The actor rule is enforced both ways: a customer attempting any sequence other than 5, or anyone other than the owning customer attempting sequence 5, is rejected with `ERR_MILESTONE_ACTOR_MISMATCH` (HTTP 403). The remaining gates, in order: the job must not be `ON_HOLD` (`ERR_JOB_ON_HOLD`); the milestone itself must currently be in `PENDING` or `REOPENED` (`ERR_INVALID_STATE`); the sequence-specific existence gates — sequence 4 additionally requires an existing tryout sample for the job in `SUBMITTED` or `BOUGHT_OFF` (`ERR_INVALID_STATE`), sequence 5 requires an existing `BOUGHT_OFF` sample, and sequence 6 requires the tool's `physical_status` to be `IN_PRODUCTION` (`ERR_INVALID_STATE`); then the actor rule of §2.7 tier 10 fires; and only after that, every milestone with a lower `seq` must already be in `EARNED`, `INVOICED`, or `PAID` (`ERR_MILESTONE_SEQUENCE_BLOCKED`). Completion stamps `completed_at` from the logical clock — and on a `PENDING` to `EARNED` move the earned amount locks at the milestone's current `planned_amount_cents`; the caller may attach an optional `completion_note`.

Billing is percentage-of-completion against the contract. At job creation the planned amounts are computed in this pinned order: for sequences 1 through 5, the planned amount is the job's `contract_value_cents` multiplied by the line's `billing_pct` and divided by one hundred, rounded half-up to integer cents per line; sequence 6 then absorbs the remainder, so the six planned amounts sum exactly to the contract value.

Once a milestone is `EARNED`, a `FinanceAdmin` issues its progress invoice, moving the milestone from `EARNED` to `INVOICED`. The invoice's `amount_cents` is the milestone's `planned_amount_cents` minus the `paid_cents` already attributed to that milestone — net-new billing, which matters after a rework reopen. This computed amount is always at least one cent, because engineering-change charges are non-negative and replanning never lowers a milestone below what has already been paid on it. The invoice records its `build_job_id` and `build_milestone_id`, and is created in `ISSUED` status with a server-minted `invoice_number` of the form INV-<job-sequence>-<n>, where `<job-sequence>` is the 1-indexed shop-wide counter of build jobs in creation order and `<n>` is the 1-indexed per-job counter of invoices issued against that job, `issued_by_user_id` set to the caller's `X-User-ID` (the segregation-of-duties anchor), and `due_date` thirty days after issuance. Issuance recomputes the job's `billed_cents`.

Customers pay, and a `FinanceAdmin` records the cash: a payment carries `amount_cents` (at least one cent) and the OCC field `expected_build_job_version`. The payment waterfall then allocates the money with no caller control over ordering. Eligible invoices are the job's invoices in `ISSUED` or `PARTIALLY_PAID` — `VOID` and `PAID` are excluded — ordered by `due_date` ascending with ties broken by `created_at` ascending (and, should `created_at` still tie, by server-internal creation order). Walking that order, each invoice receives the smaller of its `balance_due_cents` and the remaining unallocated cash; each allocation is recorded as an `invoice_id` and `applied_cents` pair in the payment's `allocations` array in allocation order, skipping any invoice that would receive zero. An invoice whose balance is fully covered moves to `PAID` — with `paid_cents` equal to `amount_cents` and `balance_due_cents` zeroed — and an invoice partially covered moves from `ISSUED` to `PARTIALLY_PAID`; both recompute `paid_cents` and `balance_due_cents`. When a milestone is in `INVOICED` and at least one of its non-`VOID` invoices exists and every such non-`VOID` invoice is `PAID`, the milestone itself bubbles up from `INVOICED` to `PAID`.

Two pre-checks run before any money moves, in this order. First the segregation-of-duties simulation: the waterfall is simulated over the eligible invoices, and if any invoice that would receive a positive allocation was issued by the same `X-User-ID` now recording the payment, the entire request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second the overpayment check: if `amount_cents` exceeds the sum of `balance_due_cents` over all eligible invoices, the entire payment is rejected with `ERR_OVERPAYMENT` and nothing is applied — the rejection is atomic. A recorded payment stamps `recorded_by_user_id`, recomputes the job's `paid_cents`, `credit_balance_cents`, `net_paid_cents`, and `outstanding_cents`, increments the job's `version`, re-evaluates the ownership-transfer rule of §3.8, and re-evaluates the customer's suspension per §2.8. Recall from §2.5 that a payment is an append-only record: it carries `id` and `created_at` but no `updated_at` or `version`. Milestones, invoices, and payments are listable; milestone and invoice lists filter by `build_job_id` and `status`, and the payment list filters by `build_job_id`.

### 3.6. Tryout, Sampling, and Buyoff

When a job is far enough along to prove the tool, a `ProjectManager` schedules a tryout round by supplying `build_job_id` and `press_reservation_id`. The job must be in `IN_BUILD` or `TRYOUT_PHASE` (`ERR_JOB_PHASE_MISMATCH`), and the referenced press reservation must still be `RESERVED` (`ERR_INVALID_STATE`). Creating the sample starts it in `SCHEDULED` with `round_number` 1, and if the job was in `IN_BUILD` the creation itself moves the job into `TRYOUT_PHASE`. The sample list filters by `build_job_id` and `status`.

Submitting the sampled parts — a `ProjectManager` action moving the sample from `SCHEDULED` to `SUBMITTED` — carries `sample_qty`, `shots_used`, and `measured_report_ref`, the dimensional layout report reference; `sample_qty` and `shots_used` each accept zero or more (a non-negative integer). Three gates apply: the job must be in `TRYOUT_PHASE` (`ERR_JOB_PHASE_MISMATCH`), the linked press reservation must still be `RESERVED` (`ERR_INVALID_STATE`), and the logical clock must fall inside the reservation's half-open window — at or after its `start_time` and strictly before its `end_time` — failing with `ERR_OUTSIDE_RESERVATION_WINDOW` otherwise. Submission feeds the tool's life accounting: the tool's `tryout_shots` increases by `shots_used`, `lifetime_shots` is recomputed, and on the first submit the tool's `physical_status` moves from `IN_BUILD` to `TRYOUT`.

Buyoff is deliberately segregated from project management: a `QualityManager` records the `decision`. A `BOUGHT_OFF` decision moves the sample to its terminal state and bubbles upward — if the job is in `TRYOUT_PHASE` it advances to `BUYOFF_PASSED`, and if the tool is in `TRYOUT` it moves to `AWAITING_SHIPMENT`; independently of those two gated moves, the warranty clock always starts at the buyoff instant: `warranty_expires_at` is set to the buyoff instant plus 730 days. A `REJECTED` decision requires `defect_codes` to be a non-empty array, enforced as a request-shape failure under §2.7 tier 3 as `ERR_INVALID_REQUEST` (the `ERR_DEFECT_CODES_REQUIRED` identifier is not used). A rejected sample lands in `REJECTED`.

Rework closes the loop. Initiating rework on a `REJECTED` sample returns it to `SCHEDULED`: `round_number` increases by one (T2, T3, and so on), and `sample_qty`, `shots_used`, `measured_report_ref`, and `defect_codes` are all reset to null for the new round. The job must be in `TRYOUT_PHASE` or `IN_BUILD` and must not be `ON_HOLD` (`ERR_JOB_ON_HOLD`); if the job had regressed to `IN_BUILD`, initiating the rework round brings it back to `TRYOUT_PHASE`. From the third round onward — when the sample's `round_number` is 3 or higher — the caller must pass `rework_authorization_id` referencing a rework authorization belonging to this job in `AUTHORIZED` or `IN_PROGRESS` status, failing with `ERR_REWORK_REQUIRES_AUTHORIZATION` otherwise; when the referenced authorization is `AUTHORIZED`, using it here moves it to `IN_PROGRESS`.

### 3.7. Engineering Changes, Re-Baselining, and Rework Authorization

Engineering changes come from both directions: a `ToolingEngineer` files shop-initiated changes with `requested_by` set to `SHOP`, and a `Customer` files customer-initiated changes with `requested_by` set to `CUSTOMER`. A mismatch between the caller's role and `requested_by` is a shape failure (`ERR_INVALID_REQUEST`), and a customer may only file against a job they own (`ERR_NOT_RESOURCE_OWNER`). The create payload carries `build_job_id`, `description`, `affects_from_milestone_seq` (from 1 to 6 — the reopen scope), and the OCC field `expected_build_job_version` (§2.5). The target job must be in `IN_BUILD`, `TRYOUT_PHASE`, `BUYOFF_PASSED`, or `READY_TO_SHIP` — filing against a job in any other state is `ERR_INVALID_STATE`, and a held job rejects with `ERR_JOB_ON_HOLD`. A filed change starts in `SUBMITTED`; filing increments the job's `version` and recomputes `open_eco_count`.

Assessment is the `ToolingEngineer`'s pricing step, moving the change from `SUBMITTED` to `IMPACT_ASSESSED` with three inputs: `rework_hours`, `scrapped_material_cost_cents`, and `lead_extension_weeks`, each zero or greater. Five money fields are computed in a pinned evaluation order, because the schedule penalty's base includes the impact cost but must exclude the penalty itself:

1. `labor_cost_cents` is `rework_hours` multiplied by the class labor rate — 14,500 cents per hour for `CLASS_101`, 13,500 for `CLASS_102`, 12,500 for `CLASS_103`, 11,500 for `CLASS_104`, 10,500 for `CLASS_105` — rounded half-up to integer cents.
2. `material_cost_cents` is `scrapped_material_cost_cents` marked up by fifteen hundredths — multiplied by 1.15 — rounded half-up to integer cents.
3. `impact_cost_cents` is the sum of the labor and material lines.
4. An interim contract value is formed as the job's current `contract_value_cents` plus `impact_cost_cents`.
5. `schedule_penalty_cents` is zero when `lead_extension_weeks` is two or fewer; the first two weeks of extension are free. Beyond that, each additional week costs one hundredth of the interim value: the extension weeks beyond two, multiplied by 0.01, multiplied by the interim value, rounded half-up to integer cents.
6. `total_charge_cents` is `impact_cost_cents` plus `schedule_penalty_cents`.

The customer then decides. Approval and rejection both require the owning customer (`ERR_NOT_RESOURCE_OWNER`). A `REJECTED` decision moves the change to `REJECTED` and merely recomputes `open_eco_count`. An `APPROVED` decision fires the full re-baseline cascade, in hops:

- **Hop 1 — authorization.** Exactly one rework authorization is created for the change, starting in `AUTHORIZED` with `authorized_cost_cents` snapshotted from `total_charge_cents`, `consumed_cost_cents` initially null, and both `engineering_change_id` and `build_job_id` set.
- **Hop 2 — contract and milestones.** The job's `contract_value_cents` increases by `total_charge_cents`. Every milestone whose `seq` is at or beyond `affects_from_milestone_seq` and whose status is `EARNED` or `INVOICED` reopens to `REOPENED`, clearing `completed_at` to null; milestones in `PENDING` at or beyond that sequence keep their status but are replanned. Replanning follows the pinned rounding order of §3.5 against the new contract value: milestones in `PENDING` or `REOPENED` get fresh per-line amounts rounded half-up, milestones in `EARNED`, `INVOICED`, or `PAID` keep their locked `planned_amount_cents`, and the highest-`seq` milestone in the replanned set absorbs the remainder so all six planned amounts sum exactly to the new `contract_value_cents`.
- **Hop 3 — invoices.** Each reopened milestone's invoices in `ISSUED` or `PARTIALLY_PAID` transition to `VOID` with `void_reason` set to ECO_REWORK. Money already collected is not clawed back by this cascade: a voided invoice's `paid_cents` remain attributed to its milestone, and that overage can surface in the job's `credit_balance_cents`. The job's `billed_cents` is recomputed and drops the voided amounts.
- **Hop 4 — regression.** If at least one milestone was reopened and the job was in `TRYOUT_PHASE`, `BUYOFF_PASSED`, or `READY_TO_SHIP`, the job regresses to `IN_BUILD`, and the tool regresses with it — `physical_status` from `TRYOUT` or `AWAITING_SHIPMENT` back to `IN_BUILD`.

Rework then executes under the authorization's cap. A `ProjectManager` may start authorized rework (`AUTHORIZED` to `IN_PROGRESS`; the tryout initiate-rework path of §3.6 can also trigger this), may cancel an unused authorization (`AUTHORIZED` to `CANCELLED`), and completes in-progress rework by reporting `actual_cost_cents`. Completion moves the authorization from `IN_PROGRESS` to `COMPLETED` and records the spend in `consumed_cost_cents`; the reported cost may not exceed `authorized_cost_cents` — an overrun is rejected with `ERR_REWORK_COST_OVERRUN` (HTTP 422), and a cost exactly equal to the authorization is allowed.

Finally, a `ToolingEngineer` verifies the implemented change, moving it from `APPROVED` to `VERIFIED` — but only once the linked rework authorization has reached `COMPLETED` or `CANCELLED` (`ERR_INVALID_STATE` otherwise). Verification recomputes `open_eco_count`. Engineering changes list with filters on `build_job_id` and `status`; rework authorizations list with filters on `build_job_id`, `engineering_change_id`, and `status`.

### 3.8. Shipping, Lien Release, and Ownership Transfer

Shipping is the moment the lien bites. A `ProjectManager` ships a tool by supplying `carrier` and `tracking_number`. The state gate is evaluated first: the tool must be in `AWAITING_SHIPMENT` and the job must be in `READY_TO_SHIP`, with any violation rejected as `ERR_INVALID_STATE`. Only after the state gate passes does the fiscal gate run: the job's `outstanding_cents` must be less than or equal to the ship threshold — the floor of fifteen hundredths of `contract_value_cents` — or the ship is refused with `ERR_RETENTION_LIEN_BLOCK` (HTTP 402). The boundary is inclusive: an outstanding balance exactly equal to the threshold ships; one cent above it does not. Shipping stamps `shipped_at` alongside the carrier details, moves the tool from `AWAITING_SHIPMENT` to `IN_TRANSIT`, and moves the job from `READY_TO_SHIP` to `SHIPPED`.

Delivery into production is a second `ProjectManager` action: the tool moves from `IN_TRANSIT` to `IN_PRODUCTION` and `delivered_at` is set. Delivery also triggers the ownership evaluation. The retention lien is released — `ownership_status` moving one-way from `SHOP_RETAINED` to `TRANSFERRED` — only when both conditions hold: `net_paid_cents` is at least `contract_value_cents`, an exact-cent test, and the tool's `physical_status` is `IN_PRODUCTION`. The evaluation runs after every recorded payment and at delivery; when transfer succeeds while the job is in `SHIPPED`, the job closes — `SHIPPED` to `CLOSED`.

Anyone may read a job's computed billing and lien summary, which exposes `build_job_id`, `contract_value_cents`, `billed_cents`, `paid_cents`, `credit_balance_cents`, `net_paid_cents`, `outstanding_cents`, `ship_release_threshold_cents` (the floored fifteen-percent threshold), `ship_release_allowed` (true exactly when `outstanding_cents` is at or under that threshold), `open_eco_count`, and `ownership_status`. Tool assets list with filters on `customer_id`, `build_job_id`, `physical_status`, and `ownership_status`.

### 3.9. Production Support: Shot Accounting, Warranty Claims, and Spare Inserts

Once a tool is in production, its life is measured in shots, and three counters on the tool track it: `tryout_shots` (the sum of `shots_used` over the job's tryout samples, which exist exactly once they have been submitted), `reported_shots` (the sum of `shots_in_period` over the tool's `ACTIVE` shot reports), and `lifetime_shots` as their sum.

The owning customer files shot reports with `tool_asset_id`, `report_period_end`, and `shots_in_period` (at least one shot). Filing requires the tool to be `IN_PRODUCTION` (`ERR_TOOL_NOT_IN_PRODUCTION`). Two monotonicity rules keep the series clean: `report_period_end` must not lie in the future (`ERR_INVALID_TIME_WINDOW`), and it must be strictly later than the period end of every prior `ACTIVE` report for the tool (`ERR_NON_MONOTONIC_SHOT_PERIOD`). Filing adds `shots_in_period` to `reported_shots` and recomputes `lifetime_shots`. A report can be backed out only by the compensating reverse action, which moves it from `ACTIVE` to `REVERSED` (reversing a non-`ACTIVE` report is `ERR_INVALID_STATE`) and subtracts its shots from `reported_shots`. Reversal is a conserved-quantity operation — a report followed by its own reversal leaves `lifetime_shots` unchanged — and it is guarded: reversing a report of S shots is blocked with `ERR_SHOT_REVERSAL_BLOCKED` whenever any warranty claim against the tool in `FILED` or `REPAIR_SCHEDULED` carries a `claimed_at_shot_count` strictly greater than the tool's `lifetime_shots` minus S, because the reversal would invalidate a claim already filed in good faith. Shot reports list in period order and filter by `tool_asset_id`.

Warranty claims are the customer's remedy when a tool fails inside its coverage. Filing requires the tool to be `IN_PRODUCTION` or `RETURNED_FOR_REPAIR` (`ERR_TOOL_NOT_IN_PRODUCTION`) and carries `tool_asset_id`, `defect_description`, and `estimated_repair_cost_cents` (at least one cent). Filing snapshots `claimed_at_shot_count` from the tool's current `lifetime_shots`. Two eligibility gates apply, in a pinned order: the time gate first — filing after `warranty_expires_at` is rejected with `ERR_WARRANTY_TIME_EXPIRED`, and when both gates would fail the time error is the one returned — then the shot gate: `claimed_at_shot_count` must be at or below the tool's `warranty_shot_limit`, with a claim exactly at the limit still covered and anything above it rejected with `ERR_WARRANTY_SHOT_LIMIT_EXCEEDED`. A filed claim starts in `FILED`.

Adjudication belongs to a `QualityManager`, who records a `decision`. A `DENY` decision requires a non-empty `denial_reason` (a shape failure under `ERR_INVALID_REQUEST` otherwise) and moves the claim to `DENIED`. An `APPROVE` decision moves the claim to `REPAIR_SCHEDULED`, computes `approved_credit_cents`, and returns the tool to the shop — `physical_status` from `IN_PRODUCTION` to `RETURNED_FOR_REPAIR`. The credit calculation first caps the repair base at the contract snapshot: the base is the smaller of `estimated_repair_cost_cents` and the tool's `contract_snapshot_cents`. What happens next depends on the `warranty_terms` copied onto the tool from its quote:

- Under `LINEAR_PRORATION`, the credit is the repair base multiplied by the fraction of shot life remaining — the shot limit minus the claim's shot-count snapshot, floored at zero, divided by the shot limit — rounded half-up to integer cents at the final step.
- Under `DECLINING_BALANCE`, the credit is the repair base multiplied by the square of that same remaining-life fraction, again rounded half-up at the final step. Identical inputs therefore yield a strictly smaller credit than linear proration whenever the snapshot lies strictly between zero shots and the limit.

When the repair is done, a `ProjectManager` closes the claim, moving it from `REPAIR_SCHEDULED` to `CLOSED` and returning the tool from `RETURNED_FOR_REPAIR` to `IN_PRODUCTION` — the warranty loop. Claims list with filters on `tool_asset_id` and `status`.

Spare inserts round out production support. A `ProjectManager` registers a spare-insert SKU for a tool with `tool_asset_id`, `insert_code`, `unit_cost_cents` (zero or more), `initial_on_hand`, and `reorder_point` (zero or more). `on_hand` initializes from `initial_on_hand`; the SKU starts `ACTIVE`, or `DEPLETED` when the initial stock is zero. The reorder flag is a derived boundary-inclusive test: `reorder_needed` is true whenever `on_hand` is less than or equal to `reorder_point`.

Allocating inserts to the customer — a sale against stock — takes a `quantity` and is gated by production: the tool must be `IN_PRODUCTION` (`ERR_TOOL_NOT_IN_PRODUCTION`), and a `DISCONTINUED` SKU refuses with `ERR_INVALID_STATE`. The quantity must be at least one and no more than `on_hand`; asking for more than the shelf holds fails with `ERR_INSUFFICIENT_STOCK`. Allocating exactly the full stock succeeds, drives `on_hand` to zero, and flips the SKU from `ACTIVE` to `DEPLETED`. Restocking takes a `quantity` of at least one, adds it to `on_hand`, and returns a `DEPLETED` SKU to `ACTIVE` once stock is positive again; both operations recompute `reorder_needed`. Discontinuation is terminal from either `ACTIVE` or `DEPLETED`. Spare inserts list with filters on `tool_asset_id` and `status`.

## 4. Endpoint Definitions

All resources are root-mounted; there are no nested URL hierarchies. Endpoints that create a new resource answer 201 Created; reads, state transitions, and all other modifications answer 200 OK. Request payloads, preconditions, and side effects for every endpoint are specified in §2 and §3; this table is the method/path/role index only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /customers | Onboard a customer | ShopAdmin |
| GET | /customers | List customers (sort `created_at` ascending) | Any |
| GET | /customers/{customerId} | Get a customer | Any |
| POST | /tool-designs | Customer submits part data for a new tool design (`revision_number` 1) | Customer |
| GET | /tool-designs | List designs (sort `created_at` ascending); filterable | Any |
| GET | /tool-designs/{designId} | Get a design | Any |
| POST | /tool-designs/{designId}/submit | Submit a design for shop review (`DRAFT` to `SUBMITTED`) | Customer |
| POST | /tool-designs/{designId}/review | Engineering review; `RELEASED` or `REJECTED` decision | ToolingEngineer |
| POST | /tool-designs/{designId}/revise | Create the next revision of a `RELEASED` or `SUBMITTED` design | ToolingEngineer |
| POST | /quotes | Create a `DRAFT` quote priced per §3.3; OCC-guarded against the design version | Estimator |
| GET | /quotes | List quotes (sort `created_at` ascending); filterable | Any |
| GET | /quotes/{quoteId} | Get a quote | Any |
| POST | /quotes/{quoteId}/issue | Issue a `DRAFT` quote; supersedes other `ISSUED` quotes for the same design | Estimator |
| POST | /quotes/{quoteId}/respond | Customer accepts or declines an `ISSUED` quote | Customer |
| POST | /build-jobs | Create a build job from an `ACCEPTED` quote; mints six milestones and the tool asset | ProjectManager |
| GET | /build-jobs | List build jobs (sort `created_at` ascending); filterable | Any |
| GET | /build-jobs/{jobId} | Get a build job with all computed fields current | Any |
| POST | /build-jobs/{jobId}/advance | Advance job status; legal targets are `IN_BUILD` from `BOOKED` and `READY_TO_SHIP` from `BUYOFF_PASSED` | ProjectManager |
| POST | /build-jobs/{jobId}/hold | Put an active job `ON_HOLD`, capturing `hold_return_state` | ProjectManager |
| POST | /build-jobs/{jobId}/resume | Resume an `ON_HOLD` job back to its `hold_return_state` | ProjectManager |
| POST | /build-jobs/{jobId}/payments | Record a customer payment; waterfall-allocates across open invoices; OCC-guarded | FinanceAdmin |
| GET | /build-jobs/{jobId}/summary | Computed billing and lien summary for a job | Any |
| GET | /build-milestones | List milestones (sort `build_job_id` ascending, then `seq` ascending); filterable | Any |
| GET | /build-milestones/{milestoneId} | Get a milestone | Any |
| POST | /build-milestones/{milestoneId}/complete | Mark a milestone `EARNED` (sequence-ordered; sequence 5 restricted to the owning customer) | ProjectManager, Customer |
| POST | /build-milestones/{milestoneId}/invoice | Issue a progress invoice for an `EARNED` milestone | FinanceAdmin |
| GET | /progress-invoices | List invoices (sort `created_at` ascending); filterable | Any |
| GET | /progress-invoices/{invoiceId} | Get an invoice | Any |
| GET | /payments | List payments (sort `created_at` ascending); filterable | Any |
| GET | /payments/{paymentId} | Get a payment, including its allocations | Any |
| POST | /tryout-samples | Schedule a tryout round against a `RESERVED` press window; first sample moves the job to `TRYOUT_PHASE` | ProjectManager |
| GET | /tryout-samples | List tryout samples (sort `created_at` ascending); filterable | Any |
| GET | /tryout-samples/{sampleId} | Get a tryout sample | Any |
| POST | /tryout-samples/{sampleId}/submit | Submit sampled parts inside the press window; shots accrue to tool life | ProjectManager |
| POST | /tryout-samples/{sampleId}/buyoff-decision | Quality buyoff: `BOUGHT_OFF` or `REJECTED` | QualityManager |
| POST | /tryout-samples/{sampleId}/initiate-rework | Loop a `REJECTED` sample back to `SCHEDULED` with the next round number | ProjectManager |
| POST | /engineering-changes | File an engineering change against a job; OCC-guarded against the job version | ToolingEngineer, Customer |
| GET | /engineering-changes | List engineering changes (sort `created_at` ascending); filterable | Any |
| GET | /engineering-changes/{ecoId} | Get an engineering change | Any |
| POST | /engineering-changes/{ecoId}/assess | Tooling impact assessment; computes the five priced fields | ToolingEngineer |
| POST | /engineering-changes/{ecoId}/customer-decision | Customer approves or rejects an `IMPACT_ASSESSED` change; approval fires the re-baseline cascade | Customer |
| POST | /engineering-changes/{ecoId}/verify | Verify implemented rework once the linked authorization is `COMPLETED` or `CANCELLED` | ToolingEngineer |
| GET | /rework-authorizations | List rework authorizations (sort `created_at` ascending); filterable | Any |
| GET | /rework-authorizations/{raId} | Get a rework authorization | Any |
| POST | /rework-authorizations/{raId}/start | Start authorized rework | ProjectManager |
| POST | /rework-authorizations/{raId}/complete | Complete rework with actual cost; overrun rejected | ProjectManager |
| POST | /rework-authorizations/{raId}/cancel | Cancel an unused authorization | ProjectManager |
| GET | /tool-assets | List tool assets (sort `created_at` ascending); filterable | Any |
| GET | /tool-assets/{toolId} | Get a tool asset | Any |
| POST | /tool-assets/{toolId}/ship | Ship the tool; state gate first, then the retention-lien fiscal gate | ProjectManager |
| POST | /tool-assets/{toolId}/deliver | Mark delivered into production; evaluates ownership transfer | ProjectManager |
| POST | /shot-reports | Customer reports production shots for a period; monotonic per tool | Customer |
| GET | /shot-reports | List shot reports (sort `report_period_end` ascending); filterable | Any |
| GET | /shot-reports/{reportId} | Get a shot report | Any |
| POST | /shot-reports/{reportId}/reverse | Reverse an `ACTIVE` shot report; blocked when it would invalidate a filed claim | Customer |
| POST | /warranty-claims | File a warranty claim; snapshots the shot count and enforces the time and shot gates | Customer |
| GET | /warranty-claims | List warranty claims (sort `created_at` ascending); filterable | Any |
| GET | /warranty-claims/{claimId} | Get a warranty claim | Any |
| POST | /warranty-claims/{claimId}/review | Quality review: `APPROVE` computes the proration credit; `DENY` requires a reason | QualityManager |
| POST | /warranty-claims/{claimId}/close | Close a repaired claim; the tool returns to production | ProjectManager |
| POST | /spare-inserts | Register a spare-insert SKU for a tool | ProjectManager |
| GET | /spare-inserts | List spare inserts (sort `created_at` ascending); filterable | Any |
| GET | /spare-inserts/{insertId} | Get a spare insert | Any |
| POST | /spare-inserts/{insertId}/allocate | Allocate/sell inserts; requires the tool in production; quantity bounded by stock | ProjectManager |
| POST | /spare-inserts/{insertId}/restock | Restock inserts; a `DEPLETED` SKU returns to `ACTIVE` | ProjectManager |
| POST | /spare-inserts/{insertId}/discontinue | Discontinue a spare insert | ProjectManager |
| POST | /press-reservations | Book a tryout press window; half-open interval; adjacency allowed; no overlap per press | ProjectManager |
| GET | /press-reservations | List press reservations (sort `start_time` ascending); filterable | Any |
| GET | /press-reservations/{resId} | Get a press reservation | Any |
| POST | /press-reservations/{resId}/cancel | Cancel a `RESERVED` press window; blocked while referenced by an open tryout sample | ProjectManager |
| POST | /machine-reservations | Reserve a machine block; four-hour cool-down buffer; 45-hour weekly capacity per machine | ProjectManager |
| GET | /machine-reservations | List machine reservations (sort `start_time` ascending); filterable | Any |
| GET | /machine-reservations/{resId} | Get a machine reservation | Any |
| POST | /machine-reservations/{resId}/cancel | Cancel a `RESERVED` machine block | ProjectManager |
| POST | /_clock/set_current_utc | Set the logical clock (must not move backward); triggers the credit-aging suspension sweep | ShopAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow lives; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM_VALUE | 400 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_TOOL_DESIGN_NOT_FOUND | 404 |
| ERR_QUOTE_NOT_FOUND | 404 |
| ERR_BUILD_JOB_NOT_FOUND | 404 |
| ERR_BUILD_MILESTONE_NOT_FOUND | 404 |
| ERR_PROGRESS_INVOICE_NOT_FOUND | 404 |
| ERR_PAYMENT_NOT_FOUND | 404 |
| ERR_TRYOUT_SAMPLE_NOT_FOUND | 404 |
| ERR_ENGINEERING_CHANGE_NOT_FOUND | 404 |
| ERR_REWORK_AUTHORIZATION_NOT_FOUND | 404 |
| ERR_TOOL_ASSET_NOT_FOUND | 404 |
| ERR_SHOT_REPORT_NOT_FOUND | 404 |
| ERR_WARRANTY_CLAIM_NOT_FOUND | 404 |
| ERR_SPARE_INSERT_NOT_FOUND | 404 |
| ERR_PRESS_RESERVATION_NOT_FOUND | 404 |
| ERR_MACHINE_RESERVATION_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_JOB_ON_HOLD | 409 |
| ERR_JOB_PHASE_MISMATCH | 409 |
| ERR_QUOTE_NOT_ACCEPTED | 409 |
| ERR_JOB_ALREADY_EXISTS | 409 |
| ERR_INVALID_TIME_WINDOW | 422 |
| ERR_OUTSIDE_RESERVATION_WINDOW | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_WARRANTY_TIME_EXPIRED | 422 |
| ERR_WARRANTY_SHOT_LIMIT_EXCEEDED | 422 |
| ERR_PRESS_DOUBLE_BOOKED | 409 |
| ERR_MACHINE_WINDOW_CONFLICT | 409 |
| ERR_MACHINE_CAPACITY_EXCEEDED | 409 |
| ERR_MILESTONE_SEQUENCE_BLOCKED | 409 |
| ERR_MILESTONE_ACTOR_MISMATCH | 403 |
| ERR_DUPLICATE_RELEASED_DESIGN | 409 |
| ERR_NON_MONOTONIC_SHOT_PERIOD | 409 |
| ERR_SHOT_REVERSAL_BLOCKED | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_REWORK_REQUIRES_AUTHORIZATION | 409 |
| ERR_REWORK_COST_OVERRUN | 422 |
| ERR_LEAD_TIME_INFEASIBLE | 422 |
| ERR_NO_CAPACITY_RESERVED | 409 |
| ERR_CUSTOMER_SUSPENDED | 409 |
| ERR_DESIGN_NOT_RELEASED | 409 |
| ERR_TOOL_NOT_IN_PRODUCTION | 409 |
| ERR_OVERPAYMENT | 422 |
| ERR_RETENTION_LIEN_BLOCK | 402 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_STALE_TOOL_DESIGN_VERSION | 412 |
| ERR_STALE_BUILD_JOB_VERSION | 412 |
