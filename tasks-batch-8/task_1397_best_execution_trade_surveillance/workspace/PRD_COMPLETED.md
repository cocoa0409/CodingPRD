# Best Execution Trade Surveillance API — Product Requirements Document

## 1. Introduction

Broker-dealers operate under a continuous regulatory obligation to demonstrate that client orders receive the best reasonably available execution, that routing decisions and payment-for-order-flow (PFOF) arrangements are disclosed accurately, and that neither employees nor the firm itself abuses advance knowledge of client flow. This document specifies a surveillance-unit platform that supports the full compliance cycle: measuring execution quality by venue and order type, running periodic best-execution committee reviews, disclosing routing arrangements and PFOF economics, detecting and investigating abusive trading patterns such as front running and marking the close, policing employee personal-account dealing, reviewing electronic communications against a tunable lexicon, filing regulatory exceptions on time, and keeping firm policies and training current.

The platform is API-first and is mounted under the `/surveillance` prefix. It serves seven distinct operator populations — from operations staff ingesting drop-copy order feeds to committee members voting on quarterly reviews — under strict segregation of duties: the analyst who drafts a review may not vote on it, the employee who requests a personal-trade preclearance never adjudicates it, and the officer who publishes a disclosure does not also run the committee. A single logical clock governs every temporal rule in the system, so that deadlines, windows, sweeps, and expiry behavior are deterministic and replayable. The sections that follow define the global contracts every endpoint honors, the business workflows organized by domain concern, the complete endpoint inventory, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, identifying the operator's role. The recognized role values are exactly seven: `OpsAdmin`, `ComplianceAdmin`, `SurveillanceAnalyst`, `FilingOfficer`, `BestExAnalyst`, `CommitteeMember`, and `CoveredEmployee`. A request whose `X-User-Role` header is missing or does not name one of these seven roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The `X-User-ID` header is not separately validated, and its absence is never by itself grounds for rejection. A request whose role is recognized but not permitted for the target endpoint — or, for transition endpoints, not permitted for the requested transition target — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `CoveredEmployee`, `X-User-ID` is the `id` of the acting `Employee` record; ownership checks on any resource that references an employee — an attestation target, a personal trade, a training assignment — compare the resource's employee foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is any of `OpsAdmin`, `ComplianceAdmin`, `SurveillanceAnalyst`, `FilingOfficer`, `BestExAnalyst`, or `CommitteeMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a best-execution review or as an entry in `voter_user_ids` — but it does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, rendered from the logical clock of §2.4.
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

Requests to a path the API does not define — and requests using an unsupported method on a defined path — are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same error envelope.

### 2.3. Pagination

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. Values outside these bounds are clamped rather than rejected — a `limit` below 1 reads as 1, a `limit` above 100 reads as 100, and an `offset` below 0 reads as 0 — and a `limit` or `offset` that does not parse as an integer falls back to its default. List responses are sorted by `created_at` in ascending order unless stated otherwise, and rows whose `created_at` values tie retain their creation order (the sort is stable). The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reports the full size of the filtered result set and `has_more` indicates whether additional pages follow the returned one.

### 2.4. Logical Time and Epoch Sweeps

The platform runs on a single server-side logical clock; no rule in this document ever consults wall-clock time. At server startup the clock reads exactly 2026-08-01T00:00:00Z, and before any operator interaction it continues to read that default. An `OpsAdmin` may advance the clock through a dedicated test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. The clock is monotonic: the supplied `to_iso8601` must be greater than or equal to the current clock value, and any attempt to move it backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409).

Advancing the clock never, by itself, fires any time-based transition. All time-driven state changes are batched into an explicit **ops-run checkpoint**, an `OpsAdmin`-only capability that evaluates the current logical clock and fires every due epoch sweep in one pass: restricted-list entries activate or expire, approved-but-unexecuted personal trades lapse, attestation windows roll from current to due to lapsed, and training assignments slip to overdue. The checkpoint response reports per-category tallies — `restricted_activated`, `restricted_expired`, `preclearances_expired`, `preclearances_denied`, `attestations_due`, `attestations_lapsed`, and `training_marked_overdue` — so operators can reconcile exactly what the sweep changed. Throughout this document, the phrase "the logical now" (or simply "now") always refers to this logical clock.

### 2.5. Resource Identity, Timestamps, and Change Tracking

Every resource in the system carries four common properties. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `created_at` is fixed at creation while `updated_at` refreshes on every mutation, and the two are equal at creation. Wherever a request body supplies a timestamp, any ISO 8601 offset is honored, and a timestamp bearing no offset is interpreted as UTC. The `version` is an integer that starts at 1 at creation and increments by exactly one on every mutation of the resource, and it is the anchor for the optimistic concurrency rules in §2.6. All fifteen resource types — employees, venues, routing arrangements, orders, execution-quality snapshots, PFOF disclosures, best-execution reviews, surveillance alerts, surveillance cases, personal trades, restricted-list entries, communication-review items, lexicon policies, compliance policies, and training assignments — carry these four properties.

Where an endpoint path nests one resource beneath another, every identifier in the path — and every resource identifier supplied in the request body, such as an `arrangement_id`, a list of `snapshot_ids`, or venue identifiers — is validated left to right, and the first identifier that does not resolve to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404).

### 2.6. Optimistic Concurrency Control

Three write operations legitimately supersede work that other operators may be reading, and each is guarded by optimistic concurrency control. A client performing any of these writes must supply a field carrying the version of the parent resource as the client last observed it; if the resource's current `version` has advanced beyond that observed value, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before writing.

- Amending a routing arrangement requires `expected_arrangement_version`, matched against the arrangement's current `version`. A successful amendment increments the arrangement's `version` by one.
- Revising a published PFOF disclosure requires `expected_disclosure_version`, matched against the source disclosure's current `version`. A successful revision increments the source disclosure's `version` by one and marks the source with `has_pending_revision` set to true.
- Patching a lexicon policy — whether retuning its terms, changing its status, or both — requires `expected_lexicon_policy_version`, matched against the policy's current `version`. A successful patch increments the policy's `version` by one.

No other endpoint takes a version field; these three are the only optimistic-concurrency enforcement points in the API. In all three writes, an optional field supplied with a null value is treated as omitted.

### 2.7. Numeric Precision and Rounding

All rounding in the platform is **round half up**. Monetary amounts are carried in integer or decimal cents depending on context, and scores and basis-point deviations are integers. Per-share and per-line execution-quality improvements are rounded half up to two decimal places; improvement averages per share are rounded half up to four decimal places. PFOF accruals are rounded half up to whole integer cents per venue-month group before any cross-group summation. Detection scores are rounded half up to a whole integer only after all factors are summed — rounding the factors individually first is forbidden because it produces different integers on some inputs. The arrival midpoint used by quality and close-price calculations keeps its exact half-cent precision and is never pre-rounded. A deviation in basis points is rounded half up to a whole integer. Late-fee amounts are whole integer cents computed from whole-day increments.

### 2.8. Derived Fields, Recomputation on Read, and Freezing

Several resources expose derived values that follow a strict recomputation discipline. An employee's `open_case_count` and `training_overdue_count` are computed at read time from the current state of cases and assignments and are never stored. An execution-quality snapshot in `PROVISIONAL` status recomputes all of its metrics from current order data on every read; locking the snapshot computes the metrics one final time and freezes them, after which later order activity never changes the frozen values. A PFOF disclosure in `DRAFT` status recomputes its `venue_lines` on every read; submitting the disclosure freezes the lines and pins the covering arrangements' versions, and withdrawing a submission unfreezes the lines so they resume recomputing on read. Once frozen, values never silently recompute — a frozen surface changes only through an explicit lifecycle action defined in §3.

### 2.9. Cascading State Changes and Asymmetric Compensation

Suspension and termination propagate downward through the routing chain — venue, then arrangement, then order — and the cascade is deliberately asymmetric: reinstatement never travels back up. Suspending a venue suspends every active routing arrangement bound to it, which in turn cancels every routed-but-unexecuted order under those arrangements. Reinstating the venue restores the venue alone; arrangements stay suspended and cancelled orders stay cancelled. The same doctrine governs communications scoring: a lexicon retune that pushes a queued item's score over the escalation ceiling escalates the item and opens a case, but a retune that lowers a score never down-tiers an item. Employee termination, disclosure supersession, and policy supersession each carry their own compensations, described with their workflows in §3; where a compensation is not specified, none occurs.

### 2.10. Validation Evaluation Order

Every endpoint applies its checks in a fixed global order, so that when several violations coexist the reported error is deterministic. Authentication comes first (a missing or unrecognized role yields `ERR_UNAUTHENTICATED`), then role authorization for the endpoint and the requested transition target (`ERR_FORBIDDEN`), then resource ownership for the self-service actions (`ERR_NOT_RESOURCE_OWNER`), then existence of every path- and body-referenced identifier validated left to right (`ERR_NOT_FOUND`), then request shape — a body that fails to parse as a JSON object, required fields, types, enum membership, positive quantities, and a legally named transition target (`ERR_INVALID_REQUEST`, with the conditional limit-price rule reporting `ERR_LIMIT_PRICE_REQUIRED` instead) — then uniqueness constraints, then logical-clock monotonicity, then optimistic-concurrency version matching (`ERR_STALE_VERSION`), then state admissibility of the requested transition including terminal lockdown (`ERR_INVALID_STATE`), and finally the business gates specific to the workflow in the orders stated in §3. Terminal states admit no further transitions anywhere in the system: executed or cancelled orders, terminated arrangements and employees, locked snapshots, superseded disclosures and policies, retired lexicon policies, completed or cancelled training assignments, denied, reconciled, or expired personal trades, expired restricted-list entries, and cleared or escalated communication items are all final.

## 3. Business Logic & Workflows

### 3.1. Covered Employees: Onboarding, Employment Lifecycle, and Attestation

A `ComplianceAdmin` onboards a covered employee by supplying the employee's `full_name`, an external `employee_ref`, a `department`, and an `attestation_due_at` deadline. The `employee_ref` must be unique across all employees; a duplicate is rejected with `ERR_DUPLICATE_EMPLOYEE_REF` (HTTP 409). The `department` is one of `TRADING`, `OPERATIONS`, `COMPLIANCE`, or `EXECUTIVE`. Every employee carries two independent, parallel status dimensions.

The first dimension is `employment_status`, which begins at `ACTIVE`. A `ComplianceAdmin` may move an employee from `ACTIVE` to `ON_LEAVE` and back again; either `ACTIVE` or `ON_LEAVE` may transition to the terminal `TERMINATED`. Termination is a compensating event with three cascades, all fired at once: every personal trade of the employee still awaiting a decision (in `PRECLEARANCE_REQUESTED`) is denied with `denial_reason` set to `EMPLOYMENT_ENDED`; every approved-but-unexecuted trade (in `APPROVED`) is flipped to `EXPIRED`; and every training assignment of the employee in `ASSIGNED` or `OVERDUE` is cancelled. Terminated employees admit no further transitions on either dimension.

The second dimension is `attestation_status`, tracking whether the employee's periodic compliance attestation is current. Its initial value is computed at creation against the logical clock: if the supplied `attestation_due_at` has already been reached or passed, the employee starts `LAPSED`; otherwise, if the deadline falls within the coming thirty days, the employee starts `DUE`; otherwise the employee starts `CURRENT`. Thereafter the ops-run checkpoint drives the dimension forward: an employee in `CURRENT` moves to `DUE` once the logical now reaches thirty days before the deadline while still short of it, an employee in `DUE` moves to `LAPSED` once the now reaches the deadline, and a large clock jump can carry an employee directly from `CURRENT` to `LAPSED` when the now lands at or past the deadline without dwelling in the due window.

Attestation itself is self-service. A `CoveredEmployee` attests for their own record — the path identifier must equal the caller's `X-User-ID`, otherwise `ERR_NOT_RESOURCE_OWNER` — and may do so from `LAPSED`, from `DUE`, or early from `CURRENT`. Attestation is refused for a terminated employee with `ERR_INVALID_STATE`. A successful attestation sets `attestation_status` to `CURRENT`, stamps `last_attested_at` with the logical now (it remains null until the first attestation), and pushes `attestation_due_at` forward to the now plus 365 days; an early re-attestation from `CURRENT` refreshes the same two timestamps without changing the status value.

Two read-time counters complete the employee picture. `open_case_count` is the number of surveillance cases whose `subject_employee_id` is this employee and whose `review_status` is `OPEN`, `UNDER_INVESTIGATION`, or `REOPENED` — a disposed case stops counting unless it is later reopened. `training_overdue_count` is the number of the employee's training assignments in `OVERDUE` status. Both are recomputed on every read and both gate personal-trade preclearance, as §3.6 describes.

### 3.2. Venues, Routing Arrangements, and Client Order Flow

**Venues.** A `ComplianceAdmin` registers each execution venue with a unique `venue_code` (for example NYSE, ARCA, or XATS — a duplicate is rejected with `ERR_DUPLICATE_VENUE_CODE`), a display `name`, and a `venue_type` of `EXCHANGE`, `ATS`, or `MARKET_MAKER`. A venue is born `ACTIVE`. Suspending a venue moves it to `SUSPENDED` and fires the downward cascade of §2.9: every routing arrangement of that venue in `ACTIVE` moves to `SUSPENDED`, and each such suspension cancels the arrangement's orders still in `ROUTED`. Reinstatement moves the venue from `SUSPENDED` back to `ACTIVE` and deliberately restores nothing else — arrangements remain suspended and cancelled orders remain cancelled. A venue also reaches `SUSPENDED` without any direct operator action when a published best-execution review terminates routing to it (§3.5).

**Routing arrangements.** A routing arrangement records the commercial terms under which the firm routes client flow to one venue. It is created by a `ComplianceAdmin` with the `venue_id` it governs, a half-open effective window bounded by `effective_from` (inclusive) and `effective_to` (exclusive), a `pfof_tiers` tier table, and an informational `routing_fee_bps` expressed in basis points. The window must be well-formed — `effective_to` strictly after `effective_from`, else `ERR_INVALID_WINDOW` (HTTP 422). Each entry of `pfof_tiers` pairs a `min_monthly_shares` non-negative integer threshold with a `rate_cents_per_share` number; the table must be non-empty and sorted strictly ascending by `min_monthly_shares` — duplicate thresholds are rejected — and its first entry must carry a `min_monthly_shares` of zero. Arrangements begin in `NEGOTIATION`.

Activation moves an arrangement from `NEGOTIATION` to `ACTIVE` and enforces three gates, in this order: the arrangement's venue must be `ACTIVE` (otherwise `ERR_VENUE_SUSPENDED`); the window must still be open at the logical now — `effective_to` must lie in the future (otherwise `ERR_INVALID_WINDOW`); and the new window must not overlap any other arrangement of the same venue whose status is `NEGOTIATION`, `ACTIVE`, or `SUSPENDED` (otherwise `ERR_ARRANGEMENT_WINDOW_OVERLAP`, HTTP 409). Overlap is judged on half-open windows, so pure adjacency — one window's `effective_to` exactly equal to the next window's `effective_from` — is allowed. The same venue-gate, window-openness, and overlap checks apply when reinstating an arrangement from `SUSPENDED` back to `ACTIVE`, and the overlap rule is also enforced at creation and on every amendment. A `ComplianceAdmin` may suspend an `ACTIVE` arrangement, which cancels every order routed under it and still unexecuted; and from any non-terminal status — `NEGOTIATION`, `ACTIVE`, or `SUSPENDED` — the arrangement may move to the terminal `TERMINATED`, where termination from `ACTIVE` likewise cancels its routed orders while termination from `NEGOTIATION` or `SUSPENDED` has no order cascade.

Amendment is the optimistic-concurrency-guarded write of §2.6: the request carries `expected_arrangement_version` plus any of `pfof_tiers`, `routing_fee_bps`, `effective_from`, or `effective_to` to change. A stale version is rejected with `ERR_STALE_VERSION` (HTTP 412); a successful amendment bumps the arrangement's `version` by one and re-validates the window against the overlap rule. Amendment is forbidden on a terminated arrangement (`ERR_INVALID_STATE`). Because disclosure lines pin arrangement versions at submit time (§3.4), amending an arrangement silently invalidates any pending disclosure that pinned it — the staleness is detected lazily when that disclosure is next published.

**Client orders.** An `OpsAdmin` ingests client orders from the drop-copy feed, supplying `client_ref`, `symbol`, `side` (`BUY` or `SELL`), `quantity` in shares (which must be greater than zero), `order_type` (`MARKET`, `LIMIT`, or `MARKET_ON_CLOSE`), and the arrival quote as `arrival_nbbo_bid_cents` and `arrival_nbbo_ask_cents`, both integer cents with the bid greater than zero and the ask strictly greater than the bid. The `limit_price_cents` field is conditional: it is required when `order_type` is `LIMIT` and forbidden for any other order type, and a violation in either direction reports `ERR_LIMIT_PRICE_REQUIRED` (HTTP 422) rather than a generic shape error. New orders land in `RECEIVED`.

Routing moves an order from `RECEIVED` to `ROUTED`; the request names the target `arrangement_id`. Four gates apply, evaluated in order: the arrangement must exist (`ERR_NOT_FOUND`); the arrangement's venue must be `ACTIVE` (`ERR_VENUE_SUSPENDED`); no `ACTIVE` restricted-list entry for the order's symbol with `restriction_kind` of `ALL` or `CLIENT_ONLY` may exist (`ERR_SYMBOL_RESTRICTED`); and the arrangement itself must be `ACTIVE` with the logical now inside its half-open window (`ERR_NO_ACTIVE_ARRANGEMENT`). A successful route stamps `routed_at` with the logical now; the field is null until then.

Execution moves an order from `ROUTED` to `EXECUTED` with the supplied `executed_price_cents` and `executed_at`. Fills are always full: the executed quantity is the order's `quantity`, so no partial-fill field exists. The execution timestamp must satisfy the execution window — no earlier than the order's `created_at` and no later than the logical now — or the transition is rejected with `ERR_EXECUTION_WINDOW_VIOLATION` (HTTP 422). Execution is the firm's most sensitive moment, and two surveillance detections fire synchronously on every execution, detailed in §3.7: a forward front-running scan over prior employee trades, and, for `MARKET_ON_CLOSE` orders, a marking-the-close deviation check. Cancellation moves an order from either `RECEIVED` or `ROUTED` to the terminal `CANCELLED`, whether by direct operator action or by the arrangement suspension and termination cascades described above. Executed and cancelled orders admit no further transitions.

### 3.3. Measuring Execution Quality: Snapshots and Benchmarks

Execution quality is measured through snapshot buckets that aggregate a venue's executed orders for one calendar month under one benchmark. A `ComplianceAdmin` creates a bucket by naming its `venue_id`, `order_type`, `period_month`, and `variant`. The `period_month` is a calendar-month key in YYYY-MM format, and its scope is the half-open window from the first instant of that month up to — but not including — the first instant of the next month. The `variant` selects the benchmark and is pinned at creation, immutable thereafter: `FAR_TOUCH` measures improvement against the far touch of the NBBO (the regulatory benchmark), while `MIDPOINT` measures improvement against the NBBO midpoint (the committee benchmark). The combination of venue, order type, month, and variant is unique; a colliding creation is rejected with `ERR_DUPLICATE_SNAPSHOT` (HTTP 409). Snapshots are born `PROVISIONAL`.

A snapshot's scope is exactly the set of orders whose routing arrangement belongs to the snapshot's venue, whose `order_type` equals the snapshot's, whose status is `EXECUTED`, and whose `executed_at` falls inside the half-open month window; received, routed, and cancelled orders never count. For each in-scope order, the per-share improvement in cents depends on the pinned variant. The arrival midpoint is the exact — possibly half-cent — average of `arrival_nbbo_bid_cents` and `arrival_nbbo_ask_cents`. Under `FAR_TOUCH`, a `BUY` order's per-share improvement is the arrival ask minus the executed price, and a `SELL` order's is the executed price minus the arrival bid; the far-touch result is never lower than the midpoint result for the same order set. Under `MIDPOINT`, a `BUY` order's improvement is the midpoint minus the executed price, and a `SELL` order's is the executed price minus the midpoint.

The aggregation follows a pinned rounding order, because alternative orders yield different cents. First, each order's per-share improvement is rounded half up to two decimal places. Second, that rounded per-share figure is multiplied by the order's `quantity` and the resulting line amount is rounded half up to two decimal places. Third, `total_improvement_cents` is the sum of those line amounts across the scope, `total_quantity` is the sum of the scoped quantities, and `order_count` is the number of scoped orders. Finally, `avg_improvement_cents_per_share` is `total_improvement_cents` divided by `total_quantity`, rounded half up to four decimal places — or zero when `total_quantity` is zero. While a snapshot is `PROVISIONAL`, every read recomputes these four metrics from current order data, so the snapshot is a living view of the month.

Locking is the snapshot's only transition, performed by a `ComplianceAdmin`, and it is guarded: no in-scope order — venue and order type matching, created before the period's end — may still sit in `RECEIVED` or `ROUTED`, otherwise the lock is rejected with `ERR_UNRESOLVED_ORDERS` (HTTP 409). A successful lock computes the metrics one final time and freezes them; the snapshot becomes `LOCKED`, admits no further transitions, and later executions never change it. Only locked snapshots qualify as committee evidence (§3.5). The venue-scoped snapshot listing supports `period_month`, `status`, and `variant` filters alongside pagination, and it honors the same recompute-on-read rule for `PROVISIONAL` rows.

### 3.4. Payment-for-Order-Flow Disclosures

Once per calendar quarter the firm discloses, per venue, the PFOF it accrued. A `FilingOfficer` opens the cycle by creating a disclosure for a `quarter` — a key in YYYY-Qn format where Q1 spans January 1 up to April 1, Q2 spans April 1 up to July 1, Q3 spans July 1 up to October 1, and Q4 spans October 1 up to the following January 1 — together with a `pricing_variant` of `MARGINAL` or `RETROACTIVE` that selects the tier-evaluation mode and is pinned at creation, immutable thereafter. The first disclosure of a quarter carries `revision_number` 1 and a null `supersedes_id`. At most one non-superseded disclosure may exist per quarter; creating a second while one lives in `DRAFT`, `PENDING_APPROVAL`, or `PUBLISHED` is rejected with `ERR_DUPLICATE_DISCLOSURE` (HTTP 409), and the correct tool is the revision flow below. The `has_pending_revision` flag starts false and acts purely as an audit marker.

The disclosure's substance is its `venue_lines`, one per venue, each carrying the `venue_id`, the covering `arrangement_id` with its pinned `arrangement_version`, that venue's `total_shares`, and its accrued `pfof_cents`; `total_pfof_cents` is the sum of the per-line `pfof_cents`. The lines are ordered ascending by `venue_id`. While the disclosure is in `DRAFT`, the lines are computed on every read; submitting freezes them. Accrual works as follows. The quarter scope is every `EXECUTED` order whose `executed_at` falls inside the quarter window. Each order's covering arrangement is the arrangement belonging to the same venue as the order's routing arrangement whose half-open window contains the order's `executed_at`; because the overlap rule of §3.2 ignores terminated arrangements, a terminated arrangement's window may later be reused, so when several windows contain the execution instant the covering arrangement is the one with the latest `effective_from`. An executed order with no covering arrangement contributes nothing to the accrual; its existence instead blocks submission through the coverage gate described below. Orders are then grouped by covering arrangement and calendar month of execution, and each group's share total S is the sum of its orders' quantities.

Tier evaluation of S against the arrangement's `pfof_tiers` depends on the pinned `pricing_variant`. Under `MARGINAL`, each tier band covers only the shares between its own threshold and the next tier's threshold — the band's share count is the greater of zero and the lesser of S and the next threshold minus the band's threshold, with the final band uncapped — and each band's shares are multiplied by that band's rate, rounded half up to whole integer cents, then summed. Under `RETROACTIVE`, the single rate of the highest tier whose threshold does not exceed S applies to all S shares, and the product is rounded half up to whole integer cents; for any group whose shares cross a tier boundary the two variants produce different totals. A venue's line sums its groups' share totals into `total_shares` and its groups' per-group-rounded accruals into `pfof_cents` — the per-group rounding happens first, then the summation, and that order is pinned. The line pins the `arrangement_id` and `arrangement_version` of the arrangement covering the venue-month group whose latest execution is the most recent among the venue's groups.

Submitting — moving the disclosure from `DRAFT` to `PENDING_APPROVAL` — first enforces coverage: every `EXECUTED` order in the quarter must have a covering arrangement at its execution instant, or the submit is rejected with `ERR_UNCOVERED_VOLUME` (HTTP 409). On success the lines are computed once, frozen, and pinned as above, and `submitted_at` is stamped with the logical now. A filing officer who spots an error withdraws the submission, returning the disclosure from `PENDING_APPROVAL` to `DRAFT`; withdrawal clears the frozen lines (they recompute on the next read) and nulls `submitted_at`, and the submit–withdraw cycle may repeat as needed.

Publishing moves the disclosure from `PENDING_APPROVAL` to `PUBLISHED` and enforces staleness: for every venue line, the pinned arrangement must still exist and its current `version` must still equal the pinned `arrangement_version` — any arrangement amended since submission breaks the match and the publish is rejected with `ERR_DISCLOSURE_STALE` (HTTP 409). When a publishing disclosure carries a `supersedes_id`, the superseded disclosure moves from `PUBLISHED` to `SUPERSEDED` in the same breath; `SUPERSEDED` is terminal.

Revision is how a published disclosure is corrected. The revise action — the second OCC-guarded write of §2.6 — applies to a `PUBLISHED` disclosure, requires `expected_disclosure_version` matching the source's current `version` (else `ERR_STALE_VERSION`), and creates a brand-new `DRAFT` disclosure for the same quarter whose `revision_number` is one greater than the source's and whose `supersedes_id` points at the source. The source disclosure's `has_pending_revision` is set to true and its `version` increments by one. The new draft recomputes its lines on read like any draft, and when it eventually publishes it supersedes its source. The disclosure list endpoint supports `quarter`, `status`, and `supersedes_id` filters — the last returning exactly the revisions of a given disclosure, following the self-reference.

### 3.5. Best-Execution Committee Reviews

Each quarter, the best-execution committee reviews execution quality and decides the fate of every active venue. A `BestExAnalyst` drafts a review by naming the `quarter` under review, the `snapshot_ids` cited as evidence — a reference list of execution-quality snapshots, not a foreign key — and the `venue_decisions`, an array pairing each `venue_id` with a `determination` of `CONTINUE`, `MODIFY`, or `TERMINATE_ROUTING`. The creator's `X-User-ID` is recorded as `created_by_user_id` at creation; it is the segregation-of-duties anchor used at vote time. The review begins in `DRAFT`, with `voter_user_ids` empty.

Submitting the review to committee — `DRAFT` to `IN_COMMITTEE` — enforces three gates: `snapshot_ids` must be non-empty (`ERR_INVALID_REQUEST`); every referenced snapshot must be `LOCKED` (`ERR_SNAPSHOT_NOT_LOCKED`); and the `venue_decisions` must cover every venue currently `ACTIVE` exactly once — no active venue omitted, none duplicated (`ERR_INCOMPLETE_VENUE_DECISIONS`, HTTP 409).

While the review is `IN_COMMITTEE`, each `CommitteeMember` may cast an approval vote. Two segregation rules guard voting: the review's creator may never vote on their own review — a voter whose `X-User-ID` equals `created_by_user_id` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403) — and each committee member votes at most once per committee round, a repeat being rejected with `ERR_DUPLICATE_VOTE` (HTTP 409). Each accepted vote appends the voter's `X-User-ID` to `voter_user_ids`, and the third distinct qualifying vote — the approval quorum of three — automatically moves the review from `IN_COMMITTEE` to `APPROVED` with no further action required. A committee member may instead return the review for rework, moving it from `IN_COMMITTEE` back to `DRAFT`; returning clears `voter_user_ids`, so a resubmitted review starts its vote count from zero.

Publishing — `APPROVED` to `PUBLISHED` — is performed by a `BestExAnalyst` and is gated on disclosure: a PFOF disclosure for the same quarter must already exist in `PUBLISHED` status, otherwise the publish is rejected with `ERR_DISCLOSURE_NOT_PUBLISHED` (HTTP 409). Publication executes the committee's decisions through the three-link cascade of §2.9. Link one: every `venue_decisions` entry whose `determination` is `TERMINATE_ROUTING` moves that venue from `ACTIVE` to `SUSPENDED`. Link two: each such venue suspension suspends every `ACTIVE` routing arrangement bound to that venue. Link three: each such arrangement suspension cancels its orders still in `ROUTED`. `PUBLISHED` is the review's terminal state.

### 3.6. Personal-Account Trading Controls

Covered employees request preclearance before trading for their own account. A `CoveredEmployee` creates the request with just `symbol`, `side`, and `quantity` (greater than zero); the trade's `employee_id` is always taken from the caller's `X-User-ID` — it is never accepted from the request body. New requests land in `PRECLEARANCE_REQUESTED`.

Decision-making belongs to a `ComplianceAdmin`. Approval runs a gauntlet of gates, evaluated in this order so the reported failure is deterministic: the employee's `employment_status` must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the employee's `attestation_status` must not be `LAPSED` (`ERR_ATTESTATION_LAPSED`); the employee's `training_overdue_count` must be zero (`ERR_TRAINING_OVERDUE`); the employee's `open_case_count` must be zero (`ERR_OPEN_SURVEILLANCE_CASE`); no `ACTIVE` restricted-list entry covering the symbol with `restriction_kind` of `ALL` or `EMPLOYEE_ONLY` may exist (`ERR_SYMBOL_RESTRICTED`); and, for a `SELL` request, a minimum-holding-period rule applies — no `RECONCILED` `BUY` trade of the same employee in the same symbol may have executed within the trailing thirty days, with executions thirty full days (2,592,000 seconds) or more in the past being permissible (`ERR_MIN_HOLDING_PERIOD`, HTTP 409). An approved trade stamps `decided_at` with the logical now and sets `expires_at` to the now plus 48 hours — the employee has a two-day execution window. Denial moves the request to `DENIED` with an optional `denial_reason`; denial checks only that the request is still pending — the eligibility gauntlet gates approval alone. Both decisions stamp `decided_at`.

Execution reporting is self-service by the owning employee: the caller's `X-User-ID` must equal the trade's `employee_id` (else `ERR_NOT_RESOURCE_OWNER`), the trade must be `APPROVED`, and the reported `executed_at` must lie inside the closed window from `decided_at` through `expires_at`, both bounds inclusive (else `ERR_EXECUTION_WINDOW_VIOLATION`). The report carries `executed_price_cents` and `executed_at` and moves the trade to `EXECUTION_REPORTED`; it also fires the reverse front-running scan of §3.7 across client orders that executed shortly after the employee's trade. A `ComplianceAdmin` then reconciles the reported execution, moving the trade to the terminal `RECONCILED` and stamping `reconciled_at`.

Two system paths close out stale approvals. The ops-run checkpoint moves every `APPROVED` trade whose `expires_at` has passed to `EXPIRED`. And should the employee be terminated, the termination cascade of §3.1 denies pending requests with `denial_reason` `EMPLOYMENT_ENDED` and expires approved ones. Separately, the restricted-list activation sweep of §3.7's controls denies any still-pending request in a newly restricted symbol with `denial_reason` `RESTRICTED_LIST`. `DENIED`, `RECONCILED`, and `EXPIRED` are all terminal.

### 3.7. Trade Surveillance: Detection, Alerts, Cases, and Regulatory Filings

**Detection at execution time.** Two detectors fire the moment a client order executes. The forward front-running scan looks back one hour (3,600 seconds) from the execution instant T: every personal trade with the same `symbol`, in `EXECUTION_REPORTED` or `RECONCILED` status, whose `executed_at` falls in the window from T minus one hour (inclusive) up to T (exclusive) matches. The reverse scan fires when an employee reports an execution: every client order with the same `symbol`, in `EXECUTED` status, whose `executed_at` falls after the trade's `executed_at` (exclusive) and no later than one hour after it (inclusive) matches — note the mirror-image bounds.

Each match, in either direction, produces one `FRONT_RUNNING` alert carrying the matched employee as `subject_employee_id`, the client order as `related_order_id`, the personal trade as `related_trade_id`, and a computed `score`. The score combines three factors from the matched pair: a time factor of 50 scaled by how close the two executions are within the one-hour window (the full 50 at zero seconds apart, decaying linearly to zero at one hour, never negative); a size factor of 30 scaled by the ratio of the smaller to the larger of the two quantities; and a side factor of 20 when both legs trade the same side, zero otherwise. The three factors are summed first and the total is rounded half up to a whole integer — rounding factors individually first is forbidden. The alert's `score_inputs` echoes the audit inputs `delta_seconds`, `size_ratio`, and `same_side`. The score is immutable once computed.

The second detector guards the close. When an order of type `MARKET_ON_CLOSE` executes, the system computes the arrival midpoint (the exact, possibly half-cent, average of the arrival bid and ask), then the execution's deviation in basis points: the absolute difference between `executed_price_cents` and the midpoint, scaled by ten thousand per unit of midpoint, rounded half up to a whole integer. A deviation of 25 basis points or more — the boundary is inclusive — creates a `MARKING_THE_CLOSE` alert with a null `subject_employee_id`, the order as `related_order_id`, a null `related_trade_id`, a `score` of twice the deviation capped at 100, and `score_inputs` echoing `deviation_bps`. A deviation below 25 creates nothing.

**Alert triage.** Alerts are born `NEW`. A `SurveillanceAnalyst` acknowledges a `NEW` alert, moving it to `ACKNOWLEDGED`. From `ACKNOWLEDGED`, escalation moves the alert to `ESCALATED` and is gated on gravity: the alert's `score` must be at least 50 (`ERR_ALERT_SCORE_BELOW_ESCALATION`, HTTP 409). Closure as a false positive — from either `NEW` or `ACKNOWLEDGED` to the terminal `CLOSED_FALSE_POSITIVE` — carries the complementary gate: the `score` must be strictly below 50 (`ERR_ALERT_SCORE_ABOVE_FP_CEILING`, HTTP 409). An alert scored exactly 50 can therefore be escalated but never closed as a false positive.

Escalation links the alert to a case through a deterministic selector. The candidate set is any surveillance case whose `subject_employee_id` equals the alert's subject and whose `review_status` is `OPEN`, `UNDER_INVESTIGATION`, or `REOPENED`; the system maintains the invariant of at most one such case per subject, because auto-creation on escalation is the only creation path and it links instead whenever a candidate exists. When a candidate exists, the alert's `case_id` is set to it and the alert's id is appended to the case's `linked_alert_ids`. When none exists, a fresh case is created with the alert's subject (possibly null), `opened_from` set to `ALERT`, `review_status` `OPEN`, and the alert as its first linked alert, and the alert's `case_id` points at it. Because `MARKING_THE_CLOSE` alerts have a null subject, their candidate set is always empty and every such escalation creates a fresh subject-less case. The only way an alert moves from `ESCALATED` back to `ACKNOWLEDGED` is the case-reopen compensation below — a system transition that also clears the alert's `case_id` to null; the analyst-facing transition endpoint never performs that pair.

**Case review.** A surveillance case carries two parallel dimensions. The first, `review_status`, begins at `OPEN` and records the case's provenance in `opened_from` (`ALERT` or `COMM_REVIEW`), with `source_comm_item_id` set when a communications item spawned the case and null otherwise. A `SurveillanceAnalyst` moves a case from `OPEN` — or later from `REOPENED` — to `UNDER_INVESTIGATION`. Dispositioning moves it from `UNDER_INVESTIGATION` to `DISPOSITIONED` and requires the analyst to supply a `disposition` of `VIOLATION_CONFIRMED` or `UNFOUNDED`; the transition stamps `dispositioned_at` with the logical now. A confirmed violation simultaneously opens the filing dimension: `filing_status` moves from `NOT_REQUIRED` to `DRAFT` and `filing_due_at` is set to the disposition instant plus 30 days. An unfounded disposition leaves `filing_status` at `NOT_REQUIRED`.

Reopening moves a disposed case from `DISPOSITIONED` to `REOPENED` and is blocked while a filing is in flight — `filing_status` of `SUBMITTED` or `ACKNOWLEDGED` rejects the reopen with `ERR_FILING_IN_FLIGHT` (HTTP 409). Reopening compensates thoroughly: every linked alert drops from `ESCALATED` back to `ACKNOWLEDGED` with its `case_id` cleared; a `DRAFT` filing is voided — `filing_status` returns to `NOT_REQUIRED`, `filing_due_at` and `filing_submitted_at` are cleared, and `late_fee_cents` resets to zero; and the `disposition` and `dispositioned_at` are cleared. A reopened case returns to `UNDER_INVESTIGATION` through the same transition as a fresh one.

**Regulatory filings.** The second dimension, `filing_status`, begins at `NOT_REQUIRED` and is terminal at `ACKNOWLEDGED`. A `FilingOfficer` submits a filing, moving it from `DRAFT` to `SUBMITTED`; the submit requires the filing to be in `DRAFT` — a case whose filing never opened rejects the submit with `ERR_FILING_NOT_REQUIRED` (HTTP 409) — and likewise requires the case to stand `DISPOSITIONED` with `disposition` `VIOLATION_CONFIRMED`, otherwise the same `ERR_FILING_NOT_REQUIRED`. Each submission stamps `filing_submitted_at` with the logical now and recomputes the late fee: filing on or before `filing_due_at` — the boundary is inclusive — yields a `late_fee_cents` of zero; filing strictly late, even by one second, incurs a base fee of 50,000 cents plus 5,000 cents per whole day late (partial days discarded), capped at 500,000 cents. A regulator's acknowledgement moves the filing from `SUBMITTED` to `ACKNOWLEDGED`. A regulator's rejection returns it from `SUBMITTED` to `DRAFT` for amendment; the rejected submission's `filing_submitted_at` is retained as audit until the next submit overwrites it, and resubmission recomputes the late fee against the unchanged `filing_due_at`.

### 3.8. Communications Review and Lexicon Management

The firm captures employee communications and scores them against a tunable lexicon. A lexicon policy is created by a `ComplianceAdmin` in `DRAFT` status with a `name` and a `terms` array; each term pairs a `term` string with an integer `weight` between 1 and 100. Matching is case-insensitive substring matching against the message body, and each term counts at most once per item no matter how often it appears. At most one lexicon policy may be `ACTIVE` fleet-wide.

An `OpsAdmin` captures each communication as a review item, supplying the `channel` (`EMAIL` or `CHAT`), the `author_employee_id`, and the `body_text`; the item's `captured_at` stamps the logical now. At capture the item is scored against the currently `ACTIVE` policy: its `score` is the sum of the weights of the policy terms that appear at least once in the body, `matched_terms` echoes which terms matched, and `scored_policy_version` records the `version` of the policy that produced the score. When no policy is active, the score is zero, `matched_terms` is empty, and `scored_policy_version` is null. Capture also auto-tiers the item: a score of 100 or more lands it directly in `ESCALATED` and immediately opens a surveillance case on the author; a score of at least 40 but below 100 leaves it `QUEUED` for analyst review; and a score below 40 marks it `CLEARED` without further work.

A `SurveillanceAnalyst` works the queue: a `QUEUED` item moves to `IN_REVIEW`, and from either `QUEUED` or `IN_REVIEW` the analyst clears the item (`CLEARED`, terminal) or escalates it (`ESCALATED`, terminal). Every escalation of a communications item — manual or automatic — creates a surveillance case whose subject is the item's author, whose `opened_from` is `COMM_REVIEW`, whose `source_comm_item_id` is the item, and whose `review_status` is `OPEN`.

Lexicon retuning is the third OCC-guarded write of §2.6. A `ComplianceAdmin` patches a policy with `expected_lexicon_policy_version` (else `ERR_STALE_VERSION`) plus optional new `terms` and/or a `to_status` change, and a successful patch bumps the policy's `version` by one. Activating a `DRAFT` policy moves it to `ACTIVE` and retires whatever policy was previously active; the activation then cascades through the queue in three links. Link one: every communications item still `QUEUED` is rescored against the newly active policy — `score`, `matched_terms`, and `scored_policy_version` all refresh. Link two: each rescored item whose new score reaches 100 or more auto-escalates to `ESCALATED`. Link three: each such auto-escalation creates its `COMM_REVIEW` case. The cascade is asymmetric in the downward direction: items whose rescore drops — even below 40 — stay `QUEUED`, and items already `IN_REVIEW` are never rescored at all. Retiring the active policy (a status change from `ACTIVE` to the terminal `RETIRED`, whether directly or via another policy's activation) triggers the same rescore of `QUEUED` items against whichever policy is active afterwards — or a score of zero when none is — with the same escalation-only rule. A terms retune of the currently `ACTIVE` policy with no status change triggers the same rescore cascade; retuning a `DRAFT` policy's terms rescores nothing.

### 3.9. Compliance Policies and Training Administration

Policy management closes the compliance loop. A `ComplianceAdmin` drafts each policy version with a stable `policy_code` (for example PAT for personal-account trading), a `title`, and a human `version_label`. Multiple drafts may coexist under one `policy_code`, but at most one version per code may be `EFFECTIVE` at a time. Publishing a draft moves it from `DRAFT` to `EFFECTIVE` and fires a three-part side effect. First, the prior `EFFECTIVE` policy of the same code, if any, moves to the terminal `SUPERSEDED`. Second, training fans out: a `TrainingAssignment` is created for every employee whose `employment_status` is `ACTIVE` at publish time, each starting `ASSIGNED` with a `due_date` of the publish instant plus 30 days, and each carrying the `policy_id` of the newly effective version. Third, compensation: the superseded policy's assignments still in `ASSIGNED` or `OVERDUE` are cancelled, while completed ones are left untouched.

Training completion is self-service. A `CoveredEmployee` completes their own assignment — the caller's `X-User-ID` must equal the assignment's `employee_id`, else `ERR_NOT_RESOURCE_OWNER` — from either `ASSIGNED` or `OVERDUE`, moving it to the terminal `COMPLETED` and stamping `completed_at` with the logical now. Assignments that slip past their `due_date` are moved from `ASSIGNED` to `OVERDUE` by the ops-run checkpoint — recall from §2.4 that such flips happen only at the checkpoint, never spontaneously with the clock. Beyond supersession, assignments are also cancelled when their employee is terminated (§3.1). `COMPLETED` and `CANCELLED` are terminal. An employee's count of `OVERDUE` assignments feeds the preclearance gauntlet of §3.6, tying training hygiene directly to trading privileges. The assignment list supports `employee_id`, `policy_id`, and `status` filters.

Finally, the restricted list keeps both client and employee flow away from sensitive names. A `ComplianceAdmin` creates each entry with a `symbol`, a `restriction_kind`, and a future window: `effective_from` must lie strictly in the future at creation and `effective_to` strictly after `effective_from`, with violations rejected as `ERR_INVALID_WINDOW`. The `restriction_kind` scopes the block: `EMPLOYEE_ONLY` blocks personal-trade preclearance, `CLIENT_ONLY` blocks client order routing, and `ALL` blocks both. Entries are born `SCHEDULED`. Per symbol, a one-day buffer rule keeps restrictions from abutting: the new entry's window, widened by 86,400 seconds (one day) on both ends, must not intersect the plain window of any `SCHEDULED` or `ACTIVE` entry for the same symbol — a gap of exactly one day is allowed, one second less is rejected with `ERR_RESTRICTED_WINDOW_CONFLICT` (HTTP 409). The ops-run checkpoint activates a scheduled entry once the logical now reaches its `effective_from` while remaining short of `effective_to`, and activation immediately denies every still-pending personal-trade preclearance in that symbol with `denial_reason` `RESTRICTED_LIST`. The checkpoint expires entries — from `SCHEDULED` when a fully passed window was never activated, or from `ACTIVE` — once the now reaches `effective_to`. `EXPIRED` is terminal, and active entries gate flows as described in §3.2 and §3.6.

## 4. Endpoint Definitions

All endpoints live under the `/surveillance` prefix. Endpoints that create a new resource respond with HTTP 201 and the created resource; reads, modifications, transitions, and action endpoints respond with HTTP 200 and the affected resource (or, for the ops-run checkpoint, the tally object). Errors respond with the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /surveillance/_clock/set_current_utc | Advance the logical clock to `to_iso8601`; monotonic, no sweeps fired | OpsAdmin |
| POST | /surveillance/ops/runs | Ops-run checkpoint: fires all due epoch sweeps (restricted list, preclearances, attestations, training) | OpsAdmin |
| POST | /surveillance/employees | Create a covered employee (employment `ACTIVE`; attestation initialized from the clock) | ComplianceAdmin |
| GET | /surveillance/employees/{id} | Read an employee, including computed `open_case_count` and `training_overdue_count` | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/employees/{id}/employment-transition | Move employment status: `ACTIVE`↔`ON_LEAVE`, or to `TERMINATED` with the termination cascade | ComplianceAdmin |
| POST | /surveillance/employees/{id}/attest | Self-service attestation: status to `CURRENT`, deadline pushed out 365 days | CoveredEmployee |
| GET | /surveillance/employees/{id}/personal-trades | List an employee's personal trades; optional `status` filter | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| GET | /surveillance/employees/{id}/comm-review-items | List communication-review items authored by an employee; optional `status` filter | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/venues | Create a venue (`ACTIVE`) | ComplianceAdmin |
| GET | /surveillance/venues/{id} | Read a venue | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/venues/{id}/transition | Venue lifecycle `ACTIVE`↔`SUSPENDED`; suspension cascades to arrangements and routed orders | ComplianceAdmin |
| GET | /surveillance/venues/{id}/routing-arrangements | List a venue's routing arrangements; optional `status` filter | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| GET | /surveillance/venues/{id}/execution-quality-snapshots | List a venue's quality snapshots; `period_month`, `status`, `variant` filters; provisional rows recompute on read | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/routing-arrangements | Create a routing arrangement in `NEGOTIATION`; window overlap enforced | ComplianceAdmin |
| GET | /surveillance/routing-arrangements/{id} | Read a routing arrangement | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/routing-arrangements/{id}/transition | Arrangement lifecycle: activate, suspend, reinstate, terminate; suspension/termination cancel routed orders | ComplianceAdmin |
| POST | /surveillance/routing-arrangements/{id}/amend | Amend tiers and/or window of a non-terminated arrangement; OCC-guarded | ComplianceAdmin |
| GET | /surveillance/routing-arrangements/{id}/orders | List orders routed under an arrangement; `order_type`, `status` filters | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/orders | Ingest a client order from the drop-copy feed (`RECEIVED`) | OpsAdmin |
| POST | /surveillance/orders/{id}/transition | Order lifecycle: route, execute (fires surveillance detection), cancel | OpsAdmin |
| POST | /surveillance/execution-quality-snapshots | Create a `PROVISIONAL` snapshot bucket for venue/order-type/month/variant | ComplianceAdmin |
| POST | /surveillance/execution-quality-snapshots/{id}/lock | Freeze a snapshot's metrics; blocked while in-scope orders are unresolved | ComplianceAdmin |
| POST | /surveillance/pfof-disclosures | Create a quarter's `DRAFT` disclosure (revision 1); duplicates rejected | FilingOfficer |
| GET | /surveillance/pfof-disclosures/{id} | Read a disclosure; drafts recompute venue lines on read | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| GET | /surveillance/pfof-disclosures | List disclosures; `quarter`, `status`, `supersedes_id` filters | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/pfof-disclosures/{id}/transition | Disclosure lifecycle: submit (freeze + pin), publish (staleness gate, supersedes), withdraw | FilingOfficer |
| POST | /surveillance/pfof-disclosures/{id}/revise | Create the next revision of a published disclosure; OCC-guarded | FilingOfficer |
| POST | /surveillance/best-ex-reviews | Create a `DRAFT` committee review; creator recorded for segregation of duties | BestExAnalyst |
| GET | /surveillance/best-ex-reviews/{id} | Read a review, including `voter_user_ids` | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/best-ex-reviews/{id}/transition | Review lifecycle: submit to committee, return for rework, publish with venue cascade | BestExAnalyst, CommitteeMember |
| POST | /surveillance/best-ex-reviews/{id}/vote | Cast a committee approval vote; third distinct vote auto-approves | CommitteeMember |
| GET | /surveillance/surveillance-alerts | List alerts; `subject_employee_id`, `related_order_id`, `related_trade_id`, `case_id`, `alert_type`, `status` filters | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| GET | /surveillance/surveillance-alerts/{id} | Read an alert | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/surveillance-alerts/{id}/transition | Alert lifecycle: acknowledge, escalate (score gate, case link-or-create), close as false positive | SurveillanceAnalyst |
| GET | /surveillance/surveillance-cases | List cases; `subject_employee_id`, `source_comm_item_id`, `review_status`, `filing_status` filters | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| GET | /surveillance/surveillance-cases/{id} | Read a case, including both parallel dimensions and `late_fee_cents` | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/surveillance-cases/{id}/review-transition | Review dimension: investigate, disposition (opens filing on confirmed violation), reopen with compensation | SurveillanceAnalyst |
| POST | /surveillance/surveillance-cases/{id}/filing-transition | Filing dimension: submit (recomputes late fee), acknowledge, regulator rejection back to draft | FilingOfficer |
| POST | /surveillance/personal-trades | Request personal-trade preclearance; employee taken from the caller's identity | CoveredEmployee |
| POST | /surveillance/personal-trades/{id}/transition | Trade lifecycle: approve (eligibility gauntlet), deny, report execution (owner only), reconcile | ComplianceAdmin, CoveredEmployee |
| POST | /surveillance/restricted-list-entries | Create a `SCHEDULED` restricted-list entry; future window and one-day buffer rule | ComplianceAdmin |
| GET | /surveillance/restricted-list-entries/{id} | Read a restricted-list entry | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/comm-review-items | Capture a communication; lexicon-scored and auto-tiered at creation | OpsAdmin |
| POST | /surveillance/comm-review-items/{id}/transition | Review workflow: start review, clear, escalate (opens a case on the author) | SurveillanceAnalyst |
| POST | /surveillance/lexicon-policies | Create a lexicon policy in `DRAFT` | ComplianceAdmin |
| GET | /surveillance/lexicon-policies/{id} | Read a lexicon policy | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| PATCH | /surveillance/lexicon-policies/{id} | Retune terms and/or change status (activate, retire); OCC-guarded; queued-item rescore cascade | ComplianceAdmin |
| POST | /surveillance/compliance-policies | Create a policy version in `DRAFT` | ComplianceAdmin |
| GET | /surveillance/compliance-policies/{id} | Read a compliance policy | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/compliance-policies/{id}/publish | Publish a draft policy: supersedes prior effective, fans out training, cancels stale assignments | ComplianceAdmin |
| GET | /surveillance/training-assignments | List training assignments; `employee_id`, `policy_id`, `status` filters | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| GET | /surveillance/training-assignments/{id} | Read a training assignment | OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer, BestExAnalyst, CommitteeMember, CoveredEmployee |
| POST | /surveillance/training-assignments/{id}/complete | Owning employee completes the assignment | CoveredEmployee |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions for each error are specified in the workflow narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_LIMIT_PRICE_REQUIRED | 422 |
| ERR_DUPLICATE_VENUE_CODE | 409 |
| ERR_DUPLICATE_EMPLOYEE_REF | 409 |
| ERR_DUPLICATE_SNAPSHOT | 409 |
| ERR_DUPLICATE_DISCLOSURE | 409 |
| ERR_CLOCK_REGRESSION | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_VENUE_SUSPENDED | 409 |
| ERR_EMPLOYEE_NOT_ACTIVE | 409 |
| ERR_ATTESTATION_LAPSED | 409 |
| ERR_TRAINING_OVERDUE | 409 |
| ERR_OPEN_SURVEILLANCE_CASE | 409 |
| ERR_SYMBOL_RESTRICTED | 409 |
| ERR_MIN_HOLDING_PERIOD | 409 |
| ERR_EXECUTION_WINDOW_VIOLATION | 422 |
| ERR_INVALID_WINDOW | 422 |
| ERR_ARRANGEMENT_WINDOW_OVERLAP | 409 |
| ERR_RESTRICTED_WINDOW_CONFLICT | 409 |
| ERR_NO_ACTIVE_ARRANGEMENT | 409 |
| ERR_UNCOVERED_VOLUME | 409 |
| ERR_SNAPSHOT_NOT_LOCKED | 409 |
| ERR_DISCLOSURE_NOT_PUBLISHED | 409 |
| ERR_DISCLOSURE_STALE | 409 |
| ERR_INCOMPLETE_VENUE_DECISIONS | 409 |
| ERR_SELF_APPROVAL_FORBIDDEN | 403 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_ALERT_SCORE_BELOW_ESCALATION | 409 |
| ERR_ALERT_SCORE_ABOVE_FP_CEILING | 409 |
| ERR_FILING_NOT_REQUIRED | 409 |
| ERR_FILING_IN_FLIGHT | 409 |
| ERR_UNRESOLVED_ORDERS | 409 |
