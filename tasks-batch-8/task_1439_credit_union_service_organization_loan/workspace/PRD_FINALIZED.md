# Credit Union CUSO Participation API — Product Requirements Document

## 1. Introduction

Credit unions routinely band together through Credit Union Service Organizations (CUSOs) to share lending infrastructure, and they just as routinely buy and sell slices of each other's loan pools through participation arrangements. Both activities are heavily supervised: regulators cap how much a credit union may invest in CUSOs, examiners suspend organizations with unresolved critical findings, and participation buyers are expected to perform their own credit due diligence rather than rely on the originator. Today these obligations are tracked in spreadsheets and bilateral email threads, which makes concentration limits, remittance timeliness, and documentation cures nearly impossible to police consistently across a network.

This document specifies a network API — mounted under `/network` — that administers the full lifecycle of CUSO investment review, participation offerings and commitments, servicing and remittance settlement, documentation exception cure, loss sharing, repurchase, portfolio surveillance, and regulatory examination. The platform serves six distinct constituencies (network administrators, credit union treasury staff, regulators, CUSO officers, originator officers, and buyer officers) with strict segregation of duties, and it encodes the supervisory arithmetic — investment caps, concentration caps, day-count accrual, late penalties, loss allocation — as deterministic server-side calculations. All state changes driven by examinations, late remittances, and cure deadlines propagate automatically through the agreement-offering-certificate hierarchy so that participants always observe a consistent regulatory posture.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the acting role. A request missing either header, or presenting a role outside the declared role set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the caller's role is not permitted on the target endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The declared roles are exactly these six:

- `NetworkAdmin` — the platform operator. Registers credit unions and CUSOs, suspends and reinstates credit unions, reverses paid remittances, runs the ops-run sweep, and drives the logical clock. For this role `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `TreasuryUser` — a credit union treasury officer managing that credit union's CUSO investments. For this role `X-User-ID` is the `id` of the acting `CreditUnion`; ownership checks on any resource that references a `CreditUnion` compare the resource's foreign-key field to `X-User-ID` (for investments, the `credit_union_id` field).
- `RegulatorUser` — a regulator or examiner. Approves or rejects CUSO investments, opens and finalizes exams, and records and verifies findings. For this role `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (as `recorded_by_user_id` on `ExamFinding`) but does not compare it to any entity's `id`.
- `CUSOOfficer` — a CUSO operations officer. Owns servicing agreements, publishes surveillance reports, and submits finding remediation. For this role `X-User-ID` is the `id` of the acting `CUSO`; ownership checks compare a resource's `cuso_id` foreign key to `X-User-ID`.
- `OriginatorUser` — an originator credit union officer. Creates and opens offerings, schedules and pays remittances, submits documentation cures, reports losses, and answers repurchase cases. For this role `X-User-ID` is the `id` of the acting `CreditUnion`; ownership checks compare the servicing agreement's `originator_id` to `X-User-ID`.
- `BuyerUser` — a buyer credit union officer. Commits to offerings, performs due diligence, funds, flags documentation exceptions, verifies cures, and triggers or withdraws repurchases. For this role `X-User-ID` is the `id` of the acting `CreditUnion`; ownership checks compare a certificate's `buyer_id` to `X-User-ID`.

Where an endpoint acts on an existing resource owned by an entity-backed caller, a caller whose `X-User-ID` does not match the owning foreign key is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Concretely: a `BuyerUser` must equal the certificate's `buyer_id`; a `TreasuryUser` must equal the investment's `credit_union_id`; an `OriginatorUser` must equal the servicing agreement's `originator_id`; and a `CUSOOfficer` must equal the servicing agreement's (or the exam's) `cuso_id`.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may be at most 100; the `offset` parameter defaults to 0. List responses are sorted by `created_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether additional pages remain.

### 2.4. The Logical Clock

All notions of "now" in the system — due-date comparisons, commitment windows, cure deadlines, sweeps, and every recorded timestamp — read from a single test-driving logical clock, never from wall-clock time. At startup, before any adjustment, the clock reads exactly 2026-08-01T00:00:00Z. A `NetworkAdmin` may advance the clock by supplying a `to_iso8601` timestamp; the capability responds with the resulting `current_utc` value. Once set, the clock holds the supplied instant and never falls back to wall-clock time. Because every deadline and every cascade in this document is phrased relative to this clock, operators should treat clock advancement as the way time-based behavior is exercised deterministically.

### 2.5. Monetary Precision, Rounding, and Day-Count Conventions

All monetary amounts are integers denominated in whole cents — fields ending in `_cents` never carry fractional values. Derived monetary figures are rounded half up to zero decimal places (whole cents) unless a rule states otherwise. Regulatory caps are the deliberate exception: caps are rounded down to whole cents before any comparison, and all cap comparisons are integer comparisons.

Interest and servicing-fee accrual use a 360-day year. Each servicing agreement selects a day-count variant through its `day_count_convention`. Under `THIRTY_360`, each full calendar month in the period counts as 30 days, and a partial month counts the smaller of the actual calendar days in the period and 30 — so the window 2026-08-01 through 2026-08-31 contributes 30 days. Under `ACT_360`, the day count is the actual number of calendar days from the period start through the period end, inclusive — the same August window contributes 31 days. Identical principal, rate, and window therefore produce different accruals under the two conventions, with `ACT_360` accruing more in 31-day months.

### 2.6. Common Resource Properties and Optimistic Concurrency

Every resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format that refreshes on every mutation, and a `version` integer that increments on every mutation. All entities in this network — credit unions, CUSOs, investments, agreements, offerings, certificates, exceptions, remittances, surveillance reports, exams, findings, loss events, and repurchase cases — share this property set.

Exactly one write endpoint participates in optimistic concurrency control: publishing a surveillance report. The publish request must carry `expected_servicing_agreement_version`, a non-optional field holding the caller's last observed `version` of the target servicing agreement. Publication supersedes the agreement's prior `CURRENT` report and increments the agreement's `version` by one, so a request whose `expected_servicing_agreement_version` no longer matches the agreement's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412): the caller's view of which report is `CURRENT` is stale, and accepting the write would let it supersede a report it never observed. No other endpoint takes a version field.

### 2.7. Validation Order

The server evaluates request validation in a fixed priority order, so that when several checks would fail, the caller always sees the same error. The order is:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the six declared roles, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. This check applies to every endpoint.
2. **Role authorization** — the caller's role is listed among the endpoint's permitted roles, else `ERR_FORBIDDEN_FOR_ROLE`. This check applies to every endpoint.
3. **Resource ownership** — for action endpoints on existing resources, an entity-backed caller owns the target (buyer matches the certificate's `buyer_id`, treasury officer matches the investment's `credit_union_id`, originator matches the agreement's `originator_id`, CUSO officer matches the agreement's or exam's `cuso_id`), else `ERR_NOT_RESOURCE_OWNER`.
4. **Existence** — every identifier in the path and body resolves to an existing resource, with path identifiers resolved left to right before body identifiers, else `ERR_NOT_FOUND`.
5. **Request shape** — required fields are present, enum members are valid, integers are positive where required, and end dates fall after start dates, else `ERR_INVALID_REQUEST`. This check applies to all creation endpoints.
6. **Stale-version check** — where applicable, `expected_servicing_agreement_version` matches the agreement's current `version`, else `ERR_STALE_VERSION`.
7. **State legality** — the target resource is in a state from which the requested transition exists, else `ERR_INVALID_STATE`. This check applies to all action endpoints.
8. **Regulatory caps and segregation of duties** — the investment cap check (`ERR_INVESTMENT_CAP_EXCEEDED`, `ERR_ENHANCED_BASIS_NOT_ELIGIBLE`), the concentration cap (`ERR_CONCENTRATION_LIMIT_EXCEEDED`), and the finding-verification segregation rule (`ERR_SEGREGATION_OF_DUTIES`).
9. **Linked-entity state** — the servicing agreement is `ACTIVE` where required (`ERR_AGREEMENT_NOT_ACTIVE`), the offering is `OPEN` where required (`ERR_OFFERING_NOT_OPEN`), the credit union is `ACTIVE` for its writes (`ERR_CREDIT_UNION_NOT_ACTIVE`), the CUSO is `ACTIVE` for agreement creation and activation (`ERR_CUSO_SUSPENDED`), and no open certificates block agreement termination (`ERR_AGREEMENT_HAS_OPEN_CERTIFICATES`).
10. **Windows and deadlines** — commitments fall inside the offering window (`ERR_OFFERING_WINDOW_CLOSED`), cures arrive by the deadline (`ERR_CURE_PERIOD_EXPIRED`), exam windows do not overlap (`ERR_EXAM_WINDOW_OVERLAP`), and remittance periods do not overlap (`ERR_REMITTANCE_PERIOD_OVERLAP`).
11. **Domain constraints** — no self-participation (`ERR_SELF_PARTICIPATION`), at most one non-terminal certificate per buyer per offering (`ERR_DUPLICATE_COMMITMENT`), the minimum share is met (`ERR_MIN_SHARE_NOT_MET`), and at most one open repurchase case per certificate (`ERR_DUPLICATE_REPURCHASE_CASE`).
12. **Funds sufficiency** — the pool is not exhausted (`ERR_POOL_EXHAUSTED`), a loss does not exceed its basis (`ERR_LOSS_EXCEEDS_POOL`), at least one certificate can absorb a loss (`ERR_NO_ALLOCATABLE_CERTIFICATES`), and collections cover interest plus servicing fee (`ERR_COLLECTIONS_INSUFFICIENT`).

### 2.8. Cascading State Propagation

Status changes propagate immediately and atomically through the network's containment chains, all within the triggering request. Two master cascades exist. First, the supervisory cascade: a CUSO dropping to `SUSPENDED` drags every one of its `ACTIVE` servicing agreements to `SUSPENDED`, and each such agreement's `OPEN` offerings drop to `SUSPENDED` in turn; when the CUSO recovers to `ACTIVE`, the same chain unwinds — `SUSPENDED` agreements return to `ACTIVE` and their `SUSPENDED` offerings return to `OPEN`. Second, the delinquency cascade: a servicing agreement flipping to `DELINQUENT` suspends its `OPEN` offerings, and reinstatement from `DELINQUENT` to `ACTIVE` reopens them. Whenever any mutation touches a resource, that resource's `updated_at` refreshes and its `version` increments.

### 2.9. Regulatory Thresholds at a Glance

Several numeric thresholds recur throughout this document and are collected here for reference. A credit union's aggregate approved CUSO investment may not exceed one percent of its `total_assets_cents` under the standard basis, or three percent under the enhanced basis; the enhanced basis additionally requires the credit union's net worth ratio to be at least seven percent. A buyer's participation exposure to a single originator is capped at a configurable fraction of the buyer's `net_worth_cents`, defaulting to one quarter. Late remittances accrue a penalty of 3 basis points per day on the combined interest and principal portions. Servicing agreements default to a zero-day grace period, a thirty-day cure period, and a delinquency threshold of two late remittances. The remainder of this document defines exactly how each threshold is applied.

## 3. Business Logic & Workflows

### 3.1. Onboarding Credit Unions and CUSOs

A `NetworkAdmin` registers each participating credit union by supplying its `charter_number` (the NCUA charter number, unique across the network), its `legal_name`, its `cu_type` — one of `ORIGINATOR`, `BUYER`, or `DUAL` — plus `total_assets_cents` and `net_worth_cents`, both denominated in cents. Registration may also carry an optional `concentration_cap_pct`, the maximum share of net worth the credit union will accept as exposure to any single originator; when omitted it defaults to 0.25. A new credit union starts in `ACTIVE` status. Two figures are derived continuously: `net_worth_ratio`, the unrounded quotient of `net_worth_cents` over `total_assets_cents`, and `total_committed_principal_cents`, the sum of `committed_amount_cents` across the credit union's certificates currently in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION`.

CUSOs are registered the same way by a `NetworkAdmin`, with a `legal_name` and a `service_line` of `LENDING`, `PAYMENTS`, `COMPLIANCE`, or `TECHNOLOGY`, and likewise begin `ACTIVE`. Each CUSO continuously tracks `total_approved_investment_cents` — the sum of `amount_cents` over approved investments targeting it — and `open_critical_finding_count`, the number of findings on its exams with severity `CRITICAL` and status `OPEN`, `VERIFYING`, or `REOPENED`.

A `NetworkAdmin` may suspend an `ACTIVE` credit union, moving it to `SUSPENDED`, and reinstate a `SUSPENDED` one back to `ACTIVE`; either call against a credit union in any other posture is rejected with `ERR_INVALID_STATE`. Suspension is a gate, not a cascade: while a credit union is `SUSPENDED`, new commitments by that buyer and the opening of offerings by that originator are rejected with `ERR_CREDIT_UNION_NOT_ACTIVE`. CUSO suspension, by contrast, is never invoked directly — it is driven entirely by the examination cascade described in §3.9.

### 3.2. CUSO Investment Review and Capital Caps

A `TreasuryUser` submits an investment by naming the investing credit union via `credit_union_id` — which must equal the caller's `X-User-ID` — the target `cuso_id`, the `amount_cents` (which must be positive), and optionally the `approval_basis`. The basis is `STANDARD` when the caller expects the investment to fit within the base cap, or `ENHANCED` when the aggregate deliberately exceeds the base cap and relies on the credit union's capitalization; it defaults to `STANDARD`. A submitted investment sits in `PENDING_REVIEW` until a `RegulatorUser` decides it.

Approval is where the investment cap check runs. The base cap is the credit union's `total_assets_cents` multiplied by one percent, rounded down to whole cents; the extended cap is the same base multiplied by three percent, also rounded down. The aggregate under test is the sum of `amount_cents` across the credit union's other approved investments plus the candidate's `amount_cents`. If the aggregate does not exceed the base cap, approval is permitted under either basis. Otherwise, approval is permitted only when all of the following hold: the candidate's `approval_basis` is `ENHANCED`, the credit union's `net_worth_ratio` is at least 0.07, the target CUSO's `open_critical_finding_count` is zero, and the aggregate does not exceed the extended cap. An aggregate exactly equal to the applicable cap is allowed — rejection requires the aggregate to strictly exceed the cap. When a `STANDARD` candidate breaches the base cap the decision is rejected with `ERR_INVESTMENT_CAP_EXCEEDED`; when an `ENHANCED` candidate's eligibility conditions fail the rejection is `ERR_ENHANCED_BASIS_NOT_ELIGIBLE`; and an aggregate above the extended cap is rejected with `ERR_INVESTMENT_CAP_EXCEEDED` regardless of basis. Approving or rejecting an investment that is not in `PENDING_REVIEW` is rejected with `ERR_INVALID_STATE`.

On approval the server stamps `post_approval_aggregate_cents` with the credit union's aggregate approved investment including this one, records the clock time in `decided_at`, moves the investment to `APPROVED`, and recomputes the CUSO's `total_approved_investment_cents`. Rejection also stamps `decided_at` and moves the investment to `REJECTED`. Thereafter the investing treasury officer may rescind an `APPROVED` investment — the caller's `X-User-ID` must equal the investment's `credit_union_id`, else `ERR_NOT_RESOURCE_OWNER` — moving it to `RESCINDED` and again recomputing the CUSO's approved-investment total. `REJECTED` and `RESCINDED` are terminal.

### 3.3. Servicing Agreements: Terms, Activation, and Termination

A `CUSOOfficer` creates a servicing agreement between their CUSO and an originator credit union. The request carries the `cuso_id` — which must equal the caller's `X-User-ID` — and the `originator_id`, which must reference a credit union whose `cu_type` is `ORIGINATOR` or `DUAL`. The commercial terms are the `servicing_fee_bps` (an annualized fee in basis points of beginning-of-period outstanding principal), the `remittance_due_day` (the day of the month, from 1 through 28, on which remittances fall due in the month following each period), and the `day_count_convention` (`THIRTY_360` or `ACT_360`). Three policy knobs are optional: `grace_period_days`, the days after the due instant before a sweep escalates a scheduled remittance to late, defaulting to 0; `cure_period_days`, the days a documentation exception may remain open before escalation, defaulting to 30; and `late_remittance_threshold`, the number of currently-unpaid late remittances that flips the agreement delinquent, defaulting to 2. Each agreement also maintains `late_remittance_count`, the current number of its remittances in `LATE_UNPAID`, starting at zero. The CUSO must be `ACTIVE` at creation, else the request is rejected with `ERR_CUSO_SUSPENDED`; a new agreement starts in `DRAFT`.

Activation by the `CUSOOfficer` moves the agreement from `DRAFT` to `ACTIVE` and requires the CUSO still be `ACTIVE`, again failing with `ERR_CUSO_SUSPENDED` when it is not; activating anything other than a `DRAFT` agreement fails with `ERR_INVALID_STATE`. Termination is permitted from `DRAFT` unconditionally, and from `ACTIVE` or `DELINQUENT` only when no certificate under the agreement's offerings remains in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — otherwise the termination is rejected with `ERR_AGREEMENT_HAS_OPEN_CERTIFICATES`. `TERMINATED` is terminal. The agreement's other state movements — into and out of `DELINQUENT`, and into and out of `SUSPENDED` — are system-driven cascades covered in §3.5 and §3.9.

### 3.4. Participation Offerings and Buyer Commitments

An `OriginatorUser` lists a loan pool for participation by creating an offering under an `ACTIVE` servicing agreement — a request against an agreement in any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`, and the caller must own the agreement's `originator_id`. The offering names a human-readable `pool_name`, the total `pool_principal_cents` being offered (which must be positive), a `min_share_pct` expressing the minimum commitment as a fraction of the pool (for example 0.01 for one percent), the annualized `yield_rate_bps` passed through to participants, and the commitment window bounded by `open_at` and `close_at`, both inclusive, with `close_at` required to fall after `open_at`. An optional `loss_basis` selects how losses are shared: `OUTSTANDING`, the default, allocates pro-rata by each certificate's current `outstanding_principal_cents`, while `COMMITTED` allocates pro-rata by the original `committed_amount_cents`. Offerings begin in `DRAFT` and continuously expose `committed_principal_cents` — the sum of `committed_amount_cents` across certificates in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — and `remaining_principal_cents`, the pool principal minus that committed figure.

Opening transitions the offering from `DRAFT` to `OPEN` and is permitted only while the agreement is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) and the originator credit union is `ACTIVE` (else `ERR_CREDIT_UNION_NOT_ACTIVE`). Closing is dual-purpose: closing an `OPEN` offering moves it to `CLOSED`, while closing a `DRAFT` offering withdraws it to `WITHDRAWN`. `CLOSED`, `EXPIRED`, and `WITHDRAWN` are terminal.

A `BuyerUser` commits by supplying the `offering_id` and a `committed_amount_cents`; the certificate's `buyer_id` is always set from the caller's `X-User-ID`, and any buyer value supplied in the payload is ignored. The certificate's `share_pct` is derived as its `committed_amount_cents` divided by the offering's `pool_principal_cents`. Creation enforces a battery of checks. The offering must be `OPEN`, else `ERR_OFFERING_NOT_OPEN`. The commitment must fall within the inclusive window from `open_at` through `close_at`, else `ERR_OFFERING_WINDOW_CLOSED`. The buyer must not be the offering's originator, else `ERR_SELF_PARTICIPATION`. The buyer may hold at most one non-terminal certificate in the offering, else `ERR_DUPLICATE_COMMITMENT`. The commitment must meet the minimum share — `committed_amount_cents` at least the product of `min_share_pct` and `pool_principal_cents` — else `ERR_MIN_SHARE_NOT_MET`. And the commitment must fit the pool: `committed_amount_cents` no greater than the offering's `remaining_principal_cents`, else `ERR_POOL_EXHAUSTED`.

Concentration is checked at the same moment. The buyer's existing exposure to this originator is the sum of `committed_amount_cents` across every certificate where the buyer matches and the offering's agreement belongs to that originator, counting only certificates in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — `DECLINED`, `RESCINDED`, and `REPURCHASED` positions no longer count. The candidate exposure adds the new commitment to that sum, and the cap is the buyer's `net_worth_cents` multiplied by its `concentration_cap_pct`, rounded down to whole cents. A candidate exposure strictly above the cap is rejected with `ERR_CONCENTRATION_LIMIT_EXCEEDED`; exposure exactly equal to the cap is permitted. A successful commitment lands in `PENDING_DILIGENCE`, and the offering's `committed_principal_cents` and the buyer's `total_committed_principal_cents` are recomputed.

The buyer then completes credit due diligence. Approving diligence moves the certificate from `PENDING_DILIGENCE` to `COMMITTED`, requires the caller to equal the certificate's `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), and stamps `diligence_decision_at`. Declining moves it to `DECLINED`, stamps `diligence_decision_at` as well, and recomputes the offering and buyer aggregates, which from then on exclude the declined position. Funding a `COMMITTED` certificate moves it to `ACTIVE`: `funded_amount_cents` and `outstanding_principal_cents` are both set to `committed_amount_cents`, `funded_at` is stamped from the clock (this instant later anchors repurchase accrual when no remittances exist), and funding is only possible while the offering is `OPEN` — a `SUSPENDED` or otherwise non-`OPEN` offering rejects funding with `ERR_OFFERING_NOT_OPEN`. When a funding consumes the last of the pool so that `remaining_principal_cents` reaches zero, the offering automatically moves from `OPEN` to `CLOSED` as part of the same request. A buyer may also rescind an unfunded `COMMITTED` certificate, moving it to `RESCINDED` and recomputing the offering and buyer aggregates. `DECLINED`, `RESCINDED`, and `REPURCHASED` are the certificate's terminal states, joined by `PAID_OFF` as a non-terminal resting state the certificate can leave again (§3.5).

### 3.5. Remittance Lifecycle and Delinquency Management

Each period, the `OriginatorUser` schedules a remittance for an `ACTIVE` certificate by supplying the `certificate_id`, the inclusive `period_start` and `period_end` dates (both at 00:00:00Z, with `period_end` no earlier than `period_start`), and `collections_cents`, the total borrower collections for the period. Remittance periods for a certificate are closed intervals, and a new period that shares even a single calendar day with another non-`REVERSED` remittance of the same certificate is rejected with `ERR_REMITTANCE_PERIOD_OVERLAP`. The server derives the rest. `due_at` is the agreement's `remittance_due_day` in the month following `period_end`'s month, at 00:00:00Z. The settlement split is computed in a pinned order. First, the beginning outstanding is the certificate's `outstanding_principal_cents` before this remittance applies. Second, `servicing_fee_cents` is the beginning outstanding multiplied by the agreement's `servicing_fee_bps` divided by ten thousand, multiplied by the period's day count under the agreement's day-count convention, divided by 360, rounded half up to whole cents. Third, `interest_portion_cents` is the accrued interest for the period: the same beginning outstanding, multiplied by the offering's `yield_rate_bps` divided by ten thousand, multiplied by the day count, divided by 360, rounded half up to whole cents. Fourth, `principal_portion_cents` is the remainder — `collections_cents` minus the interest portion minus the servicing fee. A remittance whose `collections_cents` falls short of the interest plus servicing fee is rejected at creation with `ERR_COLLECTIONS_INSUFFICIENT`. A new remittance starts `SCHEDULED` with `penalty_cents` at zero and `paid_at` unset.

Payment by the `OriginatorUser` branches on timing, and always requires the remittance be in `SCHEDULED` or `LATE_UNPAID` (else `ERR_INVALID_STATE`) and the certificate be `ACTIVE` (else `ERR_INVALID_STATE`). Paying a `SCHEDULED` remittance at or before `due_at` moves it to `PAID`, stamps `paid_at`, and leaves `penalty_cents` at zero. Paying after `due_at` moves it to `PAID_LATE` and stamps a penalty: the sum of the interest and principal portions, multiplied by 3 basis points per day and by the number of calendar days from `due_at` to the payment instant, divided by ten thousand, rounded half up to whole cents. Either way the certificate's `outstanding_principal_cents` is reduced by `principal_portion_cents` and its `cumulative_interest_cents` grows by `interest_portion_cents`; if the outstanding principal thereby reaches zero, the certificate moves from `ACTIVE` to `PAID_OFF`. Paying a remittance already in `LATE_UNPAID` lands it in `PAID_LATE` with the same penalty and the same certificate balance effects, and additionally decrements the agreement's `late_remittance_count` by one; when that decrement brings the count to zero and the agreement is `DELINQUENT`, the agreement reinstates to `ACTIVE`, and its `SUSPENDED` offerings cascade back to `OPEN` in the same request.

Lateness itself is system-driven: the ops-run sweep (§3.9) flips a `SCHEDULED` remittance to `LATE_UNPAID` once the clock passes `due_at` plus the agreement's `grace_period_days`, incrementing `late_remittance_count` by one. When the incremented count reaches the agreement's `late_remittance_threshold` and the agreement is `ACTIVE`, the agreement flips to `DELINQUENT` and every `OPEN` offering under it is suspended. A `NetworkAdmin` may reverse a `PAID` or `PAID_LATE` remittance as a compensating action, moving it to `REVERSED` (terminal): the certificate's `outstanding_principal_cents` is increased back by `principal_portion_cents`, `cumulative_interest_cents` is reduced by `interest_portion_cents`, and a certificate sitting in `PAID_OFF` returns to `ACTIVE`. Reversing a remittance in any other state is rejected with `ERR_INVALID_STATE`.

### 3.6. Documentation Exceptions, Cures, and Repurchase Cases

A `BuyerUser` flags a documentation gap on a certificate by supplying the `certificate_id`, an `exception_type` of `MISSING_NOTE`, `STALE_APPRAISAL`, `INSURANCE_LAPSE`, or `UCC_FILING_GAP`, and a free-text `description`. The exception is born `OPEN` with `detected_at` stamped from the clock, a `cure_deadline` computed as `detected_at` plus the servicing agreement's `cure_period_days` calendar days, `cure_notes` unset, and `cure_attempt_count` at zero. Flagging is permitted while the certificate is in `ACTIVE` or `EXCEPTION`; against a certificate in any other state the request is rejected with `ERR_INVALID_STATE`. Creating the exception moves an `ACTIVE` certificate to `EXCEPTION`, while a certificate already in `EXCEPTION` remains `EXCEPTION`, so multiple exceptions may be open on the same certificate concurrently.

The cure loop is segregated by design: the originator submits cures and the buyer judges them. An `OriginatorUser` owning the agreement behind the certificate (else `ERR_NOT_RESOURCE_OWNER`) submits cure documentation with `cure_notes`, moving the exception from `OPEN` — or from `REJECTED`, since a rejected cure may be reattempted — to `CURE_SUBMITTED`. Each submission overwrites `cure_notes` with the latest notes and increments `cure_attempt_count` by one. Submission must arrive at or before the `cure_deadline`; the deadline is inclusive, and a submission after it is rejected with `ERR_CURE_PERIOD_EXPIRED`. A `BuyerUser` equal to the certificate's `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`) then verifies: passing `accept` as true moves the exception from `CURE_SUBMITTED` to `CURED`, while passing false moves it to `REJECTED`, from which the originator may try again until the deadline. Verifying an exception not in `CURE_SUBMITTED` is rejected with `ERR_INVALID_STATE`. When an exception is cured and no other exception of the certificate remains in `OPEN`, `CURE_SUBMITTED`, `REJECTED`, or `ESCALATED`, and no repurchase case of the certificate is in `TRIGGERED` or `DISPUTED`, the certificate returns from `EXCEPTION` to `ACTIVE`. `CURED` and `ESCALATED` are the exception's terminal states.

Escalation is the sweep's job: once the clock passes the `cure_deadline`, an exception still in `OPEN` or `REJECTED` flips to `ESCALATED`, and the same sweep auto-creates a repurchase case in `TRIGGERED` status with `trigger_reason` set to `DOCUMENTATION_DEFAULT` and `documentation_exception_id` pointing at the expired exception. A `BuyerUser` may also open a repurchase case directly by naming the `certificate_id` and a `trigger_reason` of `DOCUMENTATION_DEFAULT`, `MATERIAL_BREACH`, or `FRAUD`; buyer-created cases leave `documentation_exception_id` unset. The certificate must be `ACTIVE` or `EXCEPTION`, and at most one open case — `TRIGGERED` or `DISPUTED` — may exist per certificate, else the creation is rejected with `ERR_DUPLICATE_REPURCHASE_CASE`.

The `OriginatorUser` answers a case in one of two ways. Disputing moves it from `TRIGGERED` to `DISPUTED`. Completing it — from either `TRIGGERED` or `DISPUTED`, with the certificate in `ACTIVE` or `EXCEPTION` — stamps `repurchase_price_cents` and moves the case to `COMPLETED`. The repurchase price is the certificate's `outstanding_principal_cents` plus the accrued-but-unpaid interest: accrual runs from the day after the certificate's most recent remittance `period_end` — or from the funded date when no remittances exist — through the completion date, inclusive, using the agreement's day-count convention and the offering's yield, rounded half up to whole cents. Because loss allocations have already reduced `outstanding_principal_cents`, allocated losses are never double-counted in the price. Completion simultaneously moves the certificate to `REPURCHASED`, zeroes its `outstanding_principal_cents`, and recomputes the offering's `committed_principal_cents` and the buyer's `total_committed_principal_cents`, which thereafter exclude the repurchased position. Finally, the `BuyerUser` who owns the certificate may withdraw a `DISPUTED` case, moving it to `WITHDRAWN`; when no exceptions remain open on the certificate after the withdrawal, the certificate returns from `EXCEPTION` to `ACTIVE`. `COMPLETED` and `WITHDRAWN` are terminal for the case.

### 3.7. Loss Events and Pool-Wide Allocation

When a borrower defaults, the `OriginatorUser` reports a pool loss against an offering by supplying the `offering_id`, the `loss_amount_cents` (which must be positive), and the `defaulted_at` date of default. The loss event is recorded in `REPORTED` status with its `allocations` not yet computed.

Allocation by the `OriginatorUser` moves the event from `REPORTED` to `ALLOCATED`. Allocation requires at least one certificate of the offering in `ACTIVE` or `EXCEPTION` — otherwise it is rejected with `ERR_NO_ALLOCATABLE_CERTIFICATES` — and the `loss_amount_cents` must not exceed the total basis weight of those eligible certificates, else `ERR_LOSS_EXCEEDS_POOL`. The `loss_basis_used` is copied from the offering's `loss_basis` at allocation time and frozen on the event. Weights depend on that basis: under `OUTSTANDING` each certificate weights by its current `outstanding_principal_cents`, so paydowns shift loss share toward certificates that have paid down less; under `COMMITTED` each weights by its original `committed_amount_cents`, so the same loss produces different per-certificate shares than the outstanding basis would.

The allocation arithmetic is pinned. Each certificate's raw share is the loss amount multiplied by its weight and divided by the total weight; each share is then rounded half up to whole cents individually — the server does not sum first and round later. If the rounded shares do not sum exactly to the loss amount, the residual is distributed one cent at a time, in the residual's sign, to certificates ordered by the fractional part of their raw share from largest to smallest, breaking ties by certificate `created_at` ascending — never by identifier. Should any computed share exceed that certificate's `outstanding_principal_cents`, the share is capped at the outstanding amount and the excess is redistributed pro-rata among the uncapped certificates, repeating until the entire loss is distributed. The resulting per-certificate figures are stored on the event as `allocations`, a list of certificate and allocated-cent pairs. Each affected certificate's `outstanding_principal_cents` is reduced by its allocated amount and its `cumulative_loss_cents` grows by the same amount.

### 3.8. Surveillance Reporting

A `CUSOOfficer` publishes a surveillance report for a servicing agreement by supplying the `servicing_agreement_id`, the inclusive `period_start` and `period_end` bounds, the `expected_servicing_agreement_version` guard described in §2.6, and optionally a `weighting_basis` of `OUTSTANDING` or `COMMITTED`, defaulting to `OUTSTANDING`. Publication computes four aggregates over the pool — defined as every certificate across all of the agreement's offerings currently in `ACTIVE` or `EXCEPTION`. `total_outstanding_principal_cents` is the sum of `outstanding_principal_cents` over the pool. `active_certificate_count` is the pool's size. `delinquent_remittance_count` counts remittances of pool certificates currently in `LATE_UNPAID` at creation time. `weighted_avg_yield_bps` is the pool's weighted average coupon: each certificate's weight multiplied by its offering's `yield_rate_bps`, summed over the pool, divided by the sum of the weights, rounded half up to whole basis points. Under `OUTSTANDING` weighting the weights track current outstanding principal; under `COMMITTED` they track original committed principal, so the identical pool yields a different average coupon under the two bases. An empty pool reports a `weighted_avg_yield_bps` of zero and zeroed totals.

Every report is born `CURRENT`, and creating a new report for an agreement supersedes the agreement's prior `CURRENT` report, moving it to `SUPERSEDED` — exactly one report per agreement remains `CURRENT` at any time. Publication also increments the servicing agreement's `version` by one, which is precisely why the stale-version guard exists: a second officer publishing against an agreement version they read before a colleague's publication will be rejected with `ERR_STALE_VERSION` and must re-read the agreement.

### 3.9. Regulatory Exams, Findings, and the Ops-Run Sweep

A `RegulatorUser` opens an exam on a CUSO by supplying the `cuso_id`, a `start_date`, and an `end_date`. Exam windows are half-open — a finding or activity is in scope from `start_date` inclusive up to but not including `end_date`, both recorded at 00:00:00Z, with `end_date` required to fall after `start_date`. Windows for the same CUSO must not overlap: a new exam whose half-open window intersects an existing exam's window is rejected with `ERR_EXAM_WINDOW_OVERLAP`, though adjacency is allowed — one exam's start may equal another's end. A new exam is `IN_PROGRESS`.

Findings are recorded against the exam by a `RegulatorUser` supplying the `exam_id`, a `severity` of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL`, a `description`, and the `remediation_due_date` by which remediation must be verified. The server stamps `recorded_by_user_id` from the caller's `X-User-ID` — this anchors segregation of duties — sets the finding to `OPEN`, and recomputes the CUSO's `open_critical_finding_count`. Remediation is submitted by the `CUSOOfficer` who owns the exam's CUSO (the caller's `X-User-ID` must equal the exam's `cuso_id`, else `ERR_NOT_RESOURCE_OWNER`), supplying `remediation_notes`; this moves a finding from `OPEN`, or from `REOPENED` after a failed verification, to `VERIFYING` and stores the latest notes.

Verification is performed by a `RegulatorUser` who must not be the finding's recorder: a verifier whose `X-User-ID` equals the finding's `recorded_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Verifying with `verification_passed` true moves the finding from `VERIFYING` to `CLOSED`, its terminal state, and recomputes the CUSO's `open_critical_finding_count`; when the closed finding was `CRITICAL`, the count has fallen to zero, and the CUSO is `SUSPENDED`, the CUSO is reinstated to `ACTIVE`, cascading its `SUSPENDED` agreements back to `ACTIVE` and their `SUSPENDED` offerings back to `OPEN`. Verifying with `verification_passed` false moves the finding to `REOPENED`, returning it to the remediation loop.

Finalizing an `IN_PROGRESS` exam stamps `finalized_at` and moves it to `FINALIZED` (terminal). Finalization is the supervisory tripwire: if the exam carries at least one finding with severity `CRITICAL` still in `OPEN`, `VERIFYING`, or `REOPENED`, the CUSO flips from `ACTIVE` to `SUSPENDED`, every `ACTIVE` servicing agreement of that CUSO flips to `SUSPENDED`, and every `OPEN` offering under those agreements flips to `SUSPENDED` — certificate records are not mutated, but funding and opening are gated while the offering is suspended.

The ops-run sweep is a `NetworkAdmin` capability that executes three families of time-based transitions atomically in a single request, returning a summary with `remittances_marked_late`, `exceptions_escalated`, and `offerings_expired` counts. First, every `SCHEDULED` remittance whose `due_at` plus its agreement's `grace_period_days` lies behind the clock flips to `LATE_UNPAID`, incrementing the agreement's `late_remittance_count` and flipping the agreement to `DELINQUENT` — suspending its `OPEN` offerings — the moment the count reaches `late_remittance_threshold`. Second, every documentation exception still `OPEN` or `REJECTED` past its `cure_deadline` flips to `ESCALATED` and auto-creates a `TRIGGERED` repurchase case with `trigger_reason` `DOCUMENTATION_DEFAULT`. Third, every `OPEN` offering whose `close_at` lies behind the clock while `remaining_principal_cents` is still positive flips to `EXPIRED`, rescinding each of its certificates in `PENDING_DILIGENCE` or `COMMITTED` to `RESCINDED` and recomputing the offering's `committed_principal_cents` and each affected buyer's `total_committed_principal_cents`.

## 4. Endpoint Definitions

All endpoints live under the `/network` prefix. Endpoints that create a new resource return HTTP 201 with the created resource; endpoints that modify an existing resource (including all state-transition actions) return HTTP 200 with the updated resource; read endpoints return HTTP 200. Clients reconstruct request payloads from the narratives in §3 — the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /network/credit-unions | Register a credit union | NetworkAdmin |
| GET | /network/credit-unions/{id} | Get a credit union | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/credit-unions/{id}/suspend | Suspend a credit union | NetworkAdmin |
| POST | /network/credit-unions/{id}/reinstate | Reinstate a credit union | NetworkAdmin |
| POST | /network/cusos | Register a CUSO | NetworkAdmin |
| GET | /network/cusos/{id} | Get a CUSO | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/cuso-investments | Submit a CUSO investment for regulatory review | TreasuryUser |
| GET | /network/cuso-investments/{id} | Get an investment | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/cuso-investments | List investments (filters: `credit_union_id`, `cuso_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/cuso-investments/{id}/approve | Regulator approves investment (cap check runs here) | RegulatorUser |
| POST | /network/cuso-investments/{id}/reject | Regulator rejects investment | RegulatorUser |
| POST | /network/cuso-investments/{id}/rescind | Investor rescinds an approved investment | TreasuryUser |
| POST | /network/servicing-agreements | Create a servicing agreement between a CUSO and an originator | CUSOOfficer |
| GET | /network/servicing-agreements/{id} | Get a servicing agreement | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/servicing-agreements | List servicing agreements (filters: `cuso_id`, `originator_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/servicing-agreements/{id}/activate | Activate a draft agreement | CUSOOfficer |
| POST | /network/servicing-agreements/{id}/terminate | Terminate an agreement with no open certificates | CUSOOfficer |
| POST | /network/offerings | Create a participation offering under an agreement | OriginatorUser |
| GET | /network/offerings/{id} | Get an offering | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/offerings | List offerings (filters: `servicing_agreement_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/offerings/{id}/open | Open a draft offering for commitments | OriginatorUser |
| POST | /network/offerings/{id}/close | Close an OPEN offering or withdraw a DRAFT offering | OriginatorUser |
| POST | /network/commitments | Buyer commits to a participation share; creates a certificate in PENDING_DILIGENCE | BuyerUser |
| GET | /network/commitments/{id} | Get a certificate | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/commitments | List certificates (filters: `offering_id`, `buyer_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/commitments/{id}/approve-diligence | Buyer completes credit due diligence | BuyerUser |
| POST | /network/commitments/{id}/decline | Buyer declines after diligence | BuyerUser |
| POST | /network/commitments/{id}/fund | Buyer funds a committed certificate | BuyerUser |
| POST | /network/commitments/{id}/rescind | Buyer rescinds an unfunded commitment | BuyerUser |
| POST | /network/exceptions | Buyer flags a documentation exception on a certificate | BuyerUser |
| GET | /network/exceptions/{id} | Get an exception | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/exceptions | List exceptions (filters: `certificate_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/exceptions/{id}/submit-cure | Originator submits cure documentation | OriginatorUser |
| POST | /network/exceptions/{id}/verify-cure | Buyer accepts or rejects a submitted cure | BuyerUser |
| POST | /network/remittances | Servicer schedules a period remittance for a certificate | OriginatorUser |
| GET | /network/remittances/{id} | Get a remittance | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/remittances | List remittances (filters: `certificate_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/remittances/{id}/pay | Servicer pays a remittance (on time or late; penalty stamped if late) | OriginatorUser |
| POST | /network/remittances/{id}/reverse | Network admin reverses a paid remittance (compensating action) | NetworkAdmin |
| POST | /network/surveillance-reports | Publish a surveillance report; supersedes the prior CURRENT report (OCC on agreement version) | CUSOOfficer |
| GET | /network/surveillance-reports/{id} | Get a surveillance report | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/surveillance-reports | List surveillance reports (filters: `servicing_agreement_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/exams | Regulator opens an exam on a CUSO; half-open windows must not overlap per CUSO | RegulatorUser |
| GET | /network/exams/{id} | Get an exam | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/exams | List exams (filters: `cuso_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/exams/{id}/finalize | Finalize an exam; open CRITICAL findings suspend the CUSO (cascade) | RegulatorUser |
| POST | /network/findings | Record an exam finding | RegulatorUser |
| GET | /network/findings/{id} | Get a finding | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/findings | List findings (filters: `exam_id`, `status`, `severity`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/findings/{id}/submit-remediation | CUSO submits remediation for verification | CUSOOfficer |
| POST | /network/findings/{id}/verify | Regulator verifies remediation (must differ from recorder) | RegulatorUser |
| POST | /network/loss-events | Originator reports a pool loss | OriginatorUser |
| GET | /network/loss-events/{id} | Get a loss event | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/loss-events | List loss events (filters: `offering_id`, `status`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/loss-events/{id}/allocate | Allocate the loss pro-rata across eligible certificates | OriginatorUser |
| POST | /network/repurchase-cases | Buyer triggers a repurchase on a certificate | BuyerUser |
| GET | /network/repurchase-cases/{id} | Get a repurchase case | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| GET | /network/repurchase-cases | List repurchase cases (filters: `certificate_id`, `status`, `documentation_exception_id`) | NetworkAdmin, TreasuryUser, RegulatorUser, CUSOOfficer, OriginatorUser, BuyerUser |
| POST | /network/repurchase-cases/{id}/complete | Originator completes the repurchase (pays the repurchase price) | OriginatorUser |
| POST | /network/repurchase-cases/{id}/dispute | Originator disputes a repurchase trigger | OriginatorUser |
| POST | /network/repurchase-cases/{id}/withdraw | Buyer withdraws a disputed repurchase | BuyerUser |
| POST | /network/sweeps/run | Ops-run checkpoint: late-remittance flips, exception escalations, offering expirations, all atomic | NetworkAdmin |
| POST | /network/_clock/set_current_utc | Advance the test-driving logical clock | NetworkAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_INVESTMENT_CAP_EXCEEDED | 409 |
| ERR_ENHANCED_BASIS_NOT_ELIGIBLE | 409 |
| ERR_CONCENTRATION_LIMIT_EXCEEDED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_OFFERING_NOT_OPEN | 409 |
| ERR_CREDIT_UNION_NOT_ACTIVE | 409 |
| ERR_CUSO_SUSPENDED | 409 |
| ERR_AGREEMENT_HAS_OPEN_CERTIFICATES | 409 |
| ERR_OFFERING_WINDOW_CLOSED | 409 |
| ERR_CURE_PERIOD_EXPIRED | 409 |
| ERR_EXAM_WINDOW_OVERLAP | 409 |
| ERR_REMITTANCE_PERIOD_OVERLAP | 409 |
| ERR_SELF_PARTICIPATION | 409 |
| ERR_DUPLICATE_COMMITMENT | 409 |
| ERR_MIN_SHARE_NOT_MET | 409 |
| ERR_DUPLICATE_REPURCHASE_CASE | 409 |
| ERR_POOL_EXHAUSTED | 409 |
| ERR_LOSS_EXCEEDS_POOL | 409 |
| ERR_NO_ALLOCATABLE_CERTIFICATES | 409 |
| ERR_COLLECTIONS_INSUFFICIENT | 409 |
