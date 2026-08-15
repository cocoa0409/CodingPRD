# Wholesale Buying Group Co-op API — Product Requirements Document

## 1. Introduction

A wholesale buying group pools the purchasing volume of independent member retailers so it can negotiate tiered rebate programs with suppliers that no single member could obtain alone. Rebates earned under those programs flow back to members as quarterly pass-through distributions, while the co-op retains a contractual share of every rebate to fund its operations. This document specifies the API that administers that entire business cycle: member enrollment and lifecycle management, supplier onboarding and program negotiation, quarterly self-reported purchase volumes, independent volume audits that verify those self-reports, tiered rebate accrual with a pass-through split, quarterly distribution with a holdback reserve, and clawback recovery when members churn, fail audits, or breach exclusivity commitments.

The system is deliberately conservative about money. All rebate cash is held in an escrow pool whose balance is a running ledger, part of every distribution is withheld for a lag period before release, and any retroactive audit finding can reopen a finalized accrual and cascade through distribution, holdback, and clawback records. Five cooperating roles — operations, supplier-facing, member-facing, finance, and audit — share the workload under a segregation-of-duties model. All endpoints are mounted under the `/coop` prefix, time is reckoned in logical quarters rather than calendar dates, and every monetary figure is an integer number of cents.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). Once the headers are accepted, the role is checked against the endpoint's authorization list (see §4); a principal whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `CoopAdmin` — the co-op's operations administrator, responsible for enrollment, member lifecycle actions, and clawback administration.
- `MemberRep` — a member retailer's authorized representative, who submits purchase reports, responds to audits, and disputes clawbacks.
- `SupplierRep` — a supplier's program manager, who defines and amends programs and opens, closes, reopens, or terminates them.
- `FinanceOfficer` — the co-op's finance function, which runs the quarterly distribution calculate, approve, disburse, and reconcile steps.
- `ProgramAuditor` — the independent volume auditor, who flags reports, conducts audits, and resolves findings.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `MemberRep`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign-key field to `X-User-ID`, and a mismatch on a member-scoped operation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `SupplierRep`, `X-User-ID` is the `id` of the acting `Supplier`, and ownership checks on any resource that references a `Supplier` compare the resource's supplier foreign-key field to `X-User-ID`. When `X-User-Role` is `CoopAdmin`, `FinanceOfficer`, or `ProgramAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

All list endpoints accept two query parameters: `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100; and `offset`, defaulting to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` fails request validation with `ERR_INVALID_REQUEST` (HTTP 400); a non-integer value supplied for an integer-typed filter parameter such as `quarter_index` fails the same way. List responses are sorted by `created_at` ascending — ties broken by creation order, earliest-created first — unless otherwise noted. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether further pages remain.

### 2.4. Resource Identity, Timestamps, and Versioning

Every entity in the system — the co-op singleton, members, suppliers, supplier programs, enrollments, purchase reports, volume audits, rebate accruals, quarterly distributions, clawback cases, and holdback releases — shares the same four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 when the entity is created and increments by one on every mutation of the entity, including mutations driven by cascades from another entity's transition. Clients never supply any of these four properties; they appear in every response body.

### 2.5. The Logical Quarter Clock

Time inside the co-op advances in whole quarters, not on the wall clock. The `Coop` entity carries `current_quarter_index`, an integer quarter counter that starts at 0 — quarter 0 is open at bootstrap — and advances by exactly one each time the quarter is closed by a `CoopAdmin`. Every quarter-scoped record keys off this counter: members remember `enrolled_quarter_index` and, once churned, `churn_quarter_index`; enrollments remember `enrolled_quarter_index` and, once ended, `exit_quarter_index`; purchase reports record the `quarter_index` they cover and the `submitted_at_quarter` captured at submission time so that late reports are detectable; volume audits record `opened_quarter_index` and, upon resolution, `resolved_quarter_index`; clawback cases record `trigger_quarter_index`; and holdback releases record the `release_quarter_index` at which their cash becomes payable.

For test-driving purposes, the server also maintains a logical wall clock whose default before any adjustment is 2026-08-01T00:00:00Z. A `CoopAdmin` may set this clock by supplying `to_iso8601`; the response echoes the new logical time as `current_utc`. A missing or unparsable `to_iso8601` fails request validation with `ERR_INVALID_REQUEST` (HTTP 400). The wall clock does not advance the quarter counter — only closing the quarter does that.

### 2.6. Monetary Representation, Basis Points, and Rounding

All monetary amounts in the system — purchase volumes, rebates, holdbacks, clawbacks, pool balances — are integers denominated in cents. Rebate and split rates are expressed in basis points over a denominator of ten thousand, so 8,500 basis points means 85 percent. Whenever a multiplication by a rate is followed by division by the basis-point denominator, the result is rounded down to a whole cent, and that rounding happens exactly once, after the multiplication and division — never per intermediate step, never per tier. Percentages such as share-of-wallet are likewise integers, rounded down to a whole percentage point.

### 2.7. The Rebate Pool Ledger

The co-op keeps all undistributed rebate cash in a single escrow balance, `pool_reserve_cents` on the `Coop` entity — the aggregate undistributed rebate pool held in escrow across all quarters, initialized to 0 at bootstrap. This balance is a running ledger driven by four mutating events and nothing else. When a rebate accrual is finalized at quarter close, the accrual's `final_rebate_cents` is added to the pool, booking the supplier's rebate obligation into escrow. When a quarterly distribution is disbursed, its `net_disbursed_cents` is subtracted from the pool. When a scheduled holdback release fires, its `release_cents` is subtracted from the pool. And when a clawback case is resolved, its `recovered_cents` is added back into the pool. The pool balance must never go negative; the disbursement step is the one place where this invariant can be violated, so disbursement is refused with `ERR_INSUFFICIENT_POOL` (HTTP 409) whenever the distribution's `net_disbursed_cents` exceeds the current `pool_reserve_cents`.

Alongside the pool, the co-op tracks `retained_revenue_cents`, its lifetime retained share from all distributions. This counter starts at 0 and grows by a distribution's `total_retained_cents` at the moment that distribution is disbursed.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, because each operates on an aggregate that another session may legitimately have advanced in the meantime. All other endpoints take no version field.

Amending a supplier program's terms — the `PUT /coop/supplier-programs/{id}` operation — requires the request to carry `expected_program_version`, holding the `version` of the `SupplierProgram` the client last observed. If the program's current `version` has moved past that value — for instance because another `SupplierRep` completed a renegotiation round that supersedes the terms the caller saw — the amendment is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), and nothing is written.

Recalculating a quarterly distribution — the `POST /coop/distributions/{id}/calculate` operation — likewise requires `expected_distribution_version`, holding the client's last observed `version` of the `QuarterlyDistribution`. If the distribution's version has advanced since that observation — for instance because a late audit resolution recomputed an accrual of the distribution's quarter while the distribution was still `DRAFT` (§3.5) — the recalculation is rejected with `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412), and nothing is written.

In both cases the version field is non-optional: a request that omits it cannot be evaluated and fails request validation. On a successful guarded write, the target entity's `version` increments as usual.

### 2.9. Validation Order of Evaluation

Every request is subjected to the checks below, in exactly this order; the first failing check short-circuits the rest, and its error is the one returned. Not every check applies to every endpoint — each entry names its scope.

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and well-formed, on every endpoint. Failure: `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).
2. **Role authorization.** The role must be permitted for the endpoint per §4, on every endpoint. Failure: `ERR_FORBIDDEN` (HTTP 403).
3. **Path existence.** Resource ids templated into the URL path must resolve to existing entities, validated left to right along the path, on every resource endpoint. Failure: `ERR_NOT_FOUND` (HTTP 404).
4. **Body referential integrity.** Foreign keys supplied in the request body — for example `member_id`, `program_id`, or `purchase_report_id` — must resolve to existing entities, on every endpoint that takes foreign keys in its body. Failure: `ERR_REFERENCE_NOT_FOUND` (HTTP 422).
5. **State precondition.** The target resource must be in a state that permits the requested transition per the state rules in §3, on every state-transition endpoint. Failure: `ERR_INVALID_STATE` (HTTP 409).
6. **Pool sufficiency.** At disbursement, `pool_reserve_cents` must be at least `net_disbursed_cents`. Applies to the distribution disbursement operation only. Failure: `ERR_INSUFFICIENT_POOL` (HTTP 409).
7. **Quarter match.** A submitted purchase report's `quarter_index` must equal the co-op's `current_quarter_index` — neither an earlier (late) nor a later (early) quarter is accepted. Applies to purchase-report submission only. Failure: `ERR_QUARTER_MISMATCH` (HTTP 409).
8. **Split invariant.** At accrual finalization, `pass_through_cents` plus `retained_cents` must equal `final_rebate_cents` exactly — no cent drift is tolerated. This is a system-side sanity check during finalization rather than a client-facing check. Failure: `ERR_SPLIT_MISMATCH` (HTTP 500).
9. **Tier schedule shape.** A program's `tier_schedule` must be non-empty, strictly ascending by `min_qty` — every `min_qty` non-negative and no two tiers sharing the same `min_qty` — and every `rate_bps` must lie between 0 and 10,000 inclusive. Applies to program creation, program amendment, and program opening. Failure: `ERR_INVALID_TIER_SCHEDULE` (HTTP 422).
10. **Exclusivity threshold.** When `exclusivity_required` is true, `exclusivity_threshold_pct` must lie between 1 and 100 inclusive. Applies to program creation, program amendment, and program opening. Failure: `ERR_INVALID_EXCLUSIVITY` (HTTP 422).
11. **Program code uniqueness.** A program's `program_code` must be unique within its supplier among programs not yet `TERMINATED`; a code may be reused once the prior program carrying it has been terminated. Applies to program creation only. Failure: `ERR_DUPLICATE_PROGRAM_CODE` (HTTP 409).
12. **No future quarters.** An enrollment cannot be exited if it started in a future quarter, and a purchase report cannot be submitted for a quarter that has not started. Applies to enrollment exit and purchase-report submission. Failure: `ERR_FUTURE_QUARTER` (HTTP 409).
13. **Member active.** The member must be `ACTIVE` to enroll in a program or to submit a purchase report. Applies to enrollment creation and purchase-report submission. Failure: `ERR_MEMBER_NOT_ACTIVE` (HTTP 409).
14. **Program accepting enrollments.** The program must be `OPEN` or `REOPENED` to accept a new enrollment. Applies to enrollment creation only. Failure: `ERR_PROGRAM_NOT_OPEN` (HTTP 409).
15. **Supplier onboarded.** The supplier must be `ONBOARDED` before one of its programs can be opened. Applies to program opening only. Failure: `ERR_SUPPLIER_NOT_ONBOARDED` (HTTP 409).
16. **Program free of live enrollments.** A program cannot be terminated while it has enrollments in `ACTIVE` or `SUSPENDED` status. Applies to program termination only. Failure: `ERR_PROGRAM_HAS_ENROLLMENTS` (HTTP 409).
17. **Supplier free of live programs.** A supplier cannot be deactivated while it has programs in `OPEN`, `CLOSED_TO_NEW`, or `REOPENED` status. Applies to supplier deactivation only. Failure: `ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS` (HTTP 409).
18. **Member ownership.** For member-scoped operations — revising a purchase report, accepting audit findings, appealing audit findings, and disputing a clawback case — the caller's `X-User-ID` must equal the `id` of the member that owns the target resource. Applies to those four operations. Failure: `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
19. **No open clawbacks at reinstatement.** A suspended member cannot be reinstated while any of its clawback cases is `OPEN`, `NOTIFIED`, or `DISPUTED`. Applies to member reinstatement only. Failure: `ERR_OPEN_CLAWBACK` (HTTP 409).
20. **Program amendment freshness.** `expected_program_version` must equal the program's current `version`. Applies to program amendment only. Failure: `ERR_STALE_PROGRAM_VERSION` (HTTP 412).
21. **Distribution recalculation freshness.** `expected_distribution_version` must equal the distribution's current `version`. Applies to distribution calculation only. Failure: `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412).

Separately from this ordered pipeline, any request whose body fails schema validation — a missing required field, a value of the wrong type, a value outside a field's enumeration, or a negative amount where a non-negative one is required — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Schema validation is evaluated after check 3 (path existence) and before every later check, so a request with a malformed body aimed at a resource in a bad state draws `ERR_INVALID_REQUEST`, not `ERR_INVALID_STATE`.

### 2.10. Nested Resources and Path Resolution

Several resources live beneath their parents in the URL hierarchy: supplier programs are created beneath their supplier, purchase reports are created and listed beneath their enrollment, and the audits targeting a report are listed beneath that report. Path-templated ids are validated left to right — the parent must exist before the child beneath it is examined — and the first id that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404). Alongside the nested listing, a flat list of purchase reports exists so that reports remain reachable by foreign key: it can be filtered by `enrollment_id`, `revision_of_id`, `quarter_index`, and `status`. Other list endpoints accept their own filters, described with each workflow in §3, in addition to the standard `limit` and `offset` parameters.

## 3. Business Logic & Workflows

### 3.1. Bootstrapping the Co-op and the Quarterly Cadence

Before anything else exists, a `CoopAdmin` performs a one-time bootstrap by supplying the co-op's legal `name`. The singleton `Coop` comes into existence with `current_quarter_index` at 0, `pool_reserve_cents` at 0, and `retained_revenue_cents` at 0, and quarter 0 is immediately open for business. Bootstrapping a second time fails with `ERR_INVALID_STATE` (HTTP 409), and any operation that needs the singleton before bootstrap — including reading it — fails with `ERR_NOT_FOUND` (HTTP 404). Any permitted role may thereafter read the singleton to inspect the current quarter and the pool and retained balances.

From then on, the co-op's rhythm is the quarterly close. When a `CoopAdmin` closes the quarter, four things happen in concert: the quarter counter advances by one; every still-`OPEN` rebate accrual of the closing quarter or any earlier quarter is finalized against the best available evidence; every active enrollment has its share-of-wallet recomputed, with exclusivity breaches converted into clawback cases; and every holdback release that has come due is paid out of the pool. The full mechanics of that cascade — including the re-finalization loop when a late audit resolution changes the evidence — are developed in §3.5 and §3.6. Closing the quarter also increments the `Coop` entity's `version`.

### 3.2. Member Enrollment and the Member Lifecycle

A `CoopAdmin` enrolls a new member retailer by supplying its `legal_name` and a `commitment_level` of `BUILDER`, `STANDARD`, or `PLATINUM` — any other value fails schema validation with `ERR_INVALID_REQUEST` (HTTP 400) — the commitment tier that later governs how much of each finalized rebate reaches the member versus how much the co-op retains. The member begins life in `PENDING` status, `enrolled_quarter_index` still null, unable to participate in anything, and the roster can be listed with filters on `status` and `commitment_level`.

Activation moves the member from `PENDING` to `ACTIVE`; attempting it on a member in any other state fails with `ERR_INVALID_STATE` (HTTP 409). Activation stamps `enrolled_quarter_index` with the co-op's current quarter and increments the member's `version`.

Suspension moves an `ACTIVE` member to `SUSPENDED` — again, any other source state draws `ERR_INVALID_STATE` — and the suspension cascades: every one of the member's program enrollments currently in `ACTIVE` status moves to `SUSPENDED` alongside it, each enrollment's `version` incrementing as it flips. Reinstatement reverses the journey, moving a `SUSPENDED` member back to `ACTIVE` and flipping each of its `SUSPENDED` enrollments back to `ACTIVE`, but only while the member has no clawback case sitting in `OPEN`, `NOTIFIED`, or `DISPUTED` — an unresolved clawback blocks reinstatement with `ERR_OPEN_CLAWBACK` (HTTP 409), and a member that is not `SUSPENDED` cannot be reinstated at all (`ERR_INVALID_STATE`).

Churn is the terminal event, reachable from either `ACTIVE` or `SUSPENDED` — a member in any other state fails with `ERR_INVALID_STATE`. Whether the member was active or suspended at the time, the churn cascade is identical: `churn_quarter_index` records the current quarter; every enrollment still in `ACTIVE` or `SUSPENDED` status moves to `EXITED` with `exit_quarter_index` set to the current quarter; every holdback release still in `SCHEDULED` moves to `FORFEITED`, its cash redirected to offset what the member owes; and a clawback case with `trigger_reason` of `CHURN` is created automatically, its gross and net amounts computed per the clawback waterfall in §3.7. The member's `version` increments, and `CHURNED` admits no further transitions.

Three computed counters follow each member through this lifecycle: `lifetime_pass_through_cents`, the running sum of member-facing cash credited to the member — each disbursed distribution credits the member's pass-through share and each released holdback credits its `release_cents`, per §3.6; `lifetime_clawback_cents`, the sum of clawbacks actually recovered from the member; and `prior_audit_findings_count`, the number of the member's volume audits that resolved with a `MATERIAL` finding — the signal that later pushes the member into the elevated holdback band described in §3.6. All three start at 0.

### 3.3. Supplier Onboarding and Program Negotiation

Suppliers enter the system when a `CoopAdmin` registers one with its `legal_name` and optional free-form `onboarding_notes` capturing negotiation context (an empty string by default). The supplier starts as `PROSPECT`, and the supplier roster can be filtered by `status`. Onboarding moves a `PROSPECT` supplier to `ONBOARDED` — any other source state draws `ERR_INVALID_STATE`. Deactivation moves an `ONBOARDED` supplier to `INACTIVE`, but only while none of its programs is `OPEN`, `CLOSED_TO_NEW`, or `REOPENED`; a live program blocks deactivation with `ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS` (HTTP 409), while any programs still in `DRAFT` are swept to `TERMINATED` as part of the cascade. The supplier's `version` increments on each transition.

Programs are where the commercial terms live. A `SupplierRep` or `CoopAdmin` creates a program beneath its supplier with a supplier-scoped `program_code`, an `exclusivity_required` flag, an `exclusivity_threshold_pct`, a `tier_schedule`, and a `holdback_policy` of `FLAT` or `RISK_ADJUSTED` (any other `holdback_policy` value fails schema validation with `ERR_INVALID_REQUEST`). The program is born in `DRAFT` with `negotiation_round` at 0. Three constraints guard creation: the `tier_schedule` must be non-empty and ascending by `min_qty` with every `rate_bps` between 0 and 10,000 inclusive, else `ERR_INVALID_TIER_SCHEDULE` (HTTP 422); whenever `exclusivity_required` is true the `exclusivity_threshold_pct` must sit between 1 and 100 inclusive, else `ERR_INVALID_EXCLUSIVITY` (HTTP 422); and the `program_code` must not collide with another of the same supplier's programs that has not reached `TERMINATED`, else `ERR_DUPLICATE_PROGRAM_CODE` (HTTP 409). The program catalog can be listed and filtered by `supplier_id` and `status`.

The tier schedule deserves a careful reading, since it drives every rebate computation. It is an ordered list of tiers, each a pair of `min_qty` and `rate_bps`, sorted ascending by `min_qty`. A tier's `rate_bps` is the rebate rate, in basis points of eligible purchase cents, earned by purchase quantities at or above that tier's `min_qty`. To resolve which tier applies to a given eligible quantity, walk the schedule and select the last tier whose `min_qty` is less than or equal to the eligible quantity — qualification is inclusive, so a quantity exactly equal to a tier's `min_qty` earns that tier's rate. When the eligible quantity falls below even the first tier's `min_qty`, no scheduled tier applies and the rate is zero — equivalently, a synthetic tier with `min_qty` 0 and `rate_bps` 0 takes effect. The rebate itself is the eligible purchase cents multiplied by the selected tier's `rate_bps` and divided by ten thousand, rounded down once to a whole cent after the multiplication and division. The tier breakpoint that was actually applied is remembered on the accrual as `tier_applied_min_qty`.

A program's lifecycle is a negotiation loop. Opening moves a `DRAFT` program to `OPEN`, and re-runs the full gauntlet: the program must currently be `DRAFT` (else `ERR_INVALID_STATE`), its tier schedule and exclusivity threshold are re-validated exactly as at creation, and its parent supplier must be `ONBOARDED` — opening a program under a `PROSPECT` or `INACTIVE` supplier fails with `ERR_SUPPLIER_NOT_ONBOARDED` (HTTP 409). From `OPEN`, a `SupplierRep` may stop accepting new enrollments, moving the program to `CLOSED_TO_NEW`; from `CLOSED_TO_NEW` the program may be reopened, moving to `REOPENED`; and from `REOPENED` it may be closed to new members again, returning to `CLOSED_TO_NEW`. Each of these transitions requires the named source state (else `ERR_INVALID_STATE`) and increments the program's `version`.

Termination ends the loop from four different source states. From `OPEN`, `CLOSED_TO_NEW`, or `REOPENED`, termination is permitted only while the program has no enrollments in `ACTIVE` or `SUSPENDED` status — live enrollments block it with `ERR_PROGRAM_HAS_ENROLLMENTS` (HTTP 409). From `DRAFT`, termination is unconditional. Either way the program lands in `TERMINATED`, which is terminal, and its `version` increments.

Renegotiation happens through amendment, a `SupplierRep`-only operation guarded by optimistic concurrency: the request must carry `expected_program_version` matching the program's current `version`, or it is refused with `ERR_STALE_PROGRAM_VERSION` (HTTP 412) as described in §2.8. A successful amendment may update the `tier_schedule`, `exclusivity_required`, `exclusivity_threshold_pct`, or `holdback_policy` — the tier schedule and exclusivity threshold are re-validated under the same rules as creation — and increments both `negotiation_round` and the program's `version`. Amendments are permitted while the program is `DRAFT`, `OPEN`, `CLOSED_TO_NEW`, or `REOPENED`; a `TERMINATED` program rejects amendment with `ERR_INVALID_STATE`.

### 3.4. Enrollments and Quarterly Purchase Reporting

Enrollment is the act of joining a member to a program. A `CoopAdmin` or a `MemberRep` submits a payload containing the `member_id` and the `program_id`; both references must resolve, or the request fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 422). Two business gates then apply, in pipeline order: the member must be `ACTIVE` — a `PENDING`, `SUSPENDED`, or `CHURNED` member fails with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409) — and the program must be `OPEN` or `REOPENED`, with any other program status failing as `ERR_PROGRAM_NOT_OPEN` (HTTP 409). A successful enrollment starts in `ACTIVE` status with `enrolled_quarter_index` stamped to the current quarter; its `exit_quarter_index` stays null for as long as the enrollment remains `ACTIVE` or `SUSPENDED`. The enrollment also carries two computed exclusivity fields: `exclusivity_share_pct`, which begins at 0, and `exclusivity_status`, which begins at `COMPLIANT` when the program requires exclusivity and `NOT_APPLICABLE` otherwise; both are recomputed at every quarter close per §3.6. Enrollment records can be listed and filtered by `member_id`, `program_id`, and `status`.

A member may leave a program voluntarily: exiting moves an `ACTIVE` enrollment to `EXITED` and stamps `exit_quarter_index` with the current quarter. Exiting from any other state fails with `ERR_INVALID_STATE`, and an enrollment whose start quarter lies in the future cannot be exited — that fails with `ERR_FUTURE_QUARTER` (HTTP 409). Voluntary exit carries no clawback. Enrollments also move to `EXITED` without a client call when the member churns, as described in §3.2, and suspend and reinstate in lockstep with the member's own suspension and reinstatement cascades.

Once enrolled, the member reports its purchase volume each quarter. A `MemberRep` or `CoopAdmin` submits a report beneath the enrollment with the `quarter_index` being reported plus the self-declared figures `self_report_qty` (units) and `self_report_cents` (eligible purchase dollars in cents). Timing is strict: the `quarter_index` must equal the co-op's `current_quarter_index` exactly — an earlier quarter is late and a later quarter is early, and both are refused with `ERR_QUARTER_MISMATCH` (HTTP 409), while a quarter that has not yet started is independently refused with `ERR_FUTURE_QUARTER`; per the pipeline order in §2.9, the quarter-match check fires first. The member must also be `ACTIVE` at submission time, else `ERR_MEMBER_NOT_ACTIVE`. A report that passes these gates is recorded in `SUBMITTED` status with `submitted_at_quarter` captured for late-report auditability, and its `audited_qty` and `audited_cents` remain null until an audit resolves.

Submission immediately books a provisional rebate. The system finds or creates the `RebateAccrual` for that enrollment and quarter — the accrual starts in `OPEN` status with all computed amounts at 0 — and computes `provisional_rebate_cents` from the self-reported figures: the eligible quantity is the sum of `self_report_qty`, and the eligible cents the sum of `self_report_cents`, across all of that enrollment's non-`SUPERSEDED` reports for the quarter — repeat submissions for the same enrollment and quarter are permitted and accumulate into one accrual — and the tier resolution of §3.3 runs once over the program's schedule against those sums. The provisional amount and the applied breakpoint `tier_applied_min_qty` are stored on the accrual, awaiting quarter close. Reports for an enrollment can be listed with `quarter_index` and `status` filters, and the flat report list additionally supports `enrollment_id` and `revision_of_id` filters.

When a `ProgramAuditor` doubts a self-report, flagging moves the report from `SUBMITTED` to `FLAGGED` — any other source state draws `ERR_INVALID_STATE`. A `FLAGGED` report blocks finalization of its accrual (§3.6), so the member has an incentive to respond. The response is a revision, which only the member's own `MemberRep` may file: the role check fails with `ERR_FORBIDDEN`, and the ownership check — the caller's `X-User-ID` must equal the `id` of the member that owns the report — fails with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Revision is possible only while the report sits in `FLAGGED`; attempting to revise a report in any other state fails with `ERR_INVALID_STATE`. Revision does not edit in place. Instead, the old `FLAGGED` report transitions to `SUPERSEDED` with its `version` incremented, and a brand-new report is created in `SUBMITTED` status carrying the revised `self_report_qty` and `self_report_cents`, the same `quarter_index` as the old report, `revision_of_id` pointing back at the report it supersedes, and a fresh `submitted_at_quarter` captured at revision time. Because revision creates a new resource, it answers 201. The accrual's `provisional_rebate_cents` is then recomputed from the revised self-reported figures.

### 3.5. Volume Audits and Retroactive Adjudication

Flagging expresses suspicion; an audit establishes fact. A `ProgramAuditor` opens a volume audit by supplying the `purchase_report_id` of the specific report under examination — the reference must resolve, else `ERR_REFERENCE_NOT_FOUND` — and the audit's owning `enrollment_id` is derived from that report. The audit is born in `OPEN` status with `opened_quarter_index` stamped to the current quarter, its `resolved_quarter_index` and `finding_severity` still null. Audits can be listed and filtered by `enrollment_id`, `status`, and `finding_severity`, and the audits targeting a particular report can be listed beneath that report with a `status` filter.

From `OPEN`, the auditor begins fieldwork, moving the audit to `FIELDWORK`; from `FIELDWORK`, issuing findings moves it to `FINDINGS_ISSUED`. Each step requires its named source state, failing otherwise with `ERR_INVALID_STATE`, and increments the audit's `version`. At `FINDINGS_ISSUED` the member chooses: its own `MemberRep` may accept the findings, moving the audit to `ACCEPTED`, or appeal them, moving it to `APPEALED` — both operations enforce the ownership rule of §2.9 and reject a non-owning caller with `ERR_NOT_RESOURCE_OWNER` (and a caller without the `MemberRep` role with `ERR_FORBIDDEN`). An appealed audit is sent back to the field: the auditor reopens fieldwork, cycling the audit from `APPEALED` back to `FIELDWORK` for another pass through findings. This cycle may repeat as often as the parties require.

Resolution is the payoff. The auditor resolves an `ACCEPTED` audit — any other source state fails with `ERR_INVALID_STATE` — by attesting the final figures in the payload: `audited_qty` and `audited_cents` are both required, and their absence fails with `ERR_INVALID_REQUEST` (HTTP 400). Resolution stamps `resolved_quarter_index` with the current quarter, stores the attested `audited_qty` and `audited_cents` on the audit itself (both null until then), and computes `finding_severity` from the gap between attestation and self-report. When `audited_cents` equals the report's `self_report_cents` exactly, the severity is `NONE`. When the figures differ, the absolute difference divided by `self_report_cents` yields a discrepancy ratio: a ratio strictly greater than zero and at most five hundredths — five percent — is `MINOR`, and anything beyond that band is `MATERIAL`. When `self_report_cents` is zero and the figures differ, the ratio is undefined and the finding is `MATERIAL` by convention.

The moment of resolution fires the deepest cascade in the system. First, the audited purchase report transitions from `SUBMITTED` to `ADJUDICATED`, its `audited_qty` and `audited_cents` populated from the attestation and its `version` incremented. (If the audited report has been superseded in the meantime, it stays `SUPERSEDED` and its audited fields are not written, while the remaining cascade steps still run.) Second, the rebate accrual for that enrollment and quarter is recomputed under the final variant of tier resolution — the eligible quantity and cents are now the audited values rather than the self-reported ones, summed across the enrollment's non-`SUPERSEDED` reports for the quarter exactly as at finalization, and the result replaces `final_rebate_cents`. If the recomputed final amount differs from the accrual's prior final amount and the accrual had already been `FINALIZED`, the accrual is pulled back from `FINALIZED` to `OPEN` — with its `version` incremented — so that the next quarter close re-finalizes it on the corrected evidence. Any recomputation that changes the final amount also increments the `version` of every still-`DRAFT` distribution covering that accrual's quarter, so a later `calculate` carrying a pre-resolution `expected_distribution_version` is refused as stale (§2.8). Third, when the finding is `MATERIAL`, the member's `prior_audit_findings_count` increments by one, which pushes future distribution holdbacks into the elevated band described in §3.6. And fourth, when the finding is `MATERIAL` and the affected accrual had already been `DISTRIBUTED`, the system automatically opens a clawback case with `trigger_reason` of `AUDIT_SHORTFALL`, computed per the waterfall in §3.7. The audit's own `version` increments as it lands in the terminal `RESOLVED` state.

One nuance governs which reports may be audited: an audit can be opened only against a `SUBMITTED` report — attempting to open one against a report in any other status fails with `ERR_INVALID_STATE` (HTTP 409) — and the flag-and-revise loop of §3.4 exists so questionable reports can be corrected before an adjudication hardens the numbers. A `SUPERSEDED` report is dead history — its successor carries the live figures.

### 3.6. Quarter Close, Distribution Calculation, and Disbursement

The quarterly close is where provisional numbers harden into money. When a `CoopAdmin` closes the quarter, the `current_quarter_index` first advances by one; the quarter that was current when the close began is the closing quarter. Four cascades then run.

First, accrual finalization. Every `RebateAccrual` still in `OPEN` status whose `quarter_index` is the closing quarter or any earlier quarter — including an accrual pulled back to `OPEN` by a late audit resolution per §3.5, which is thereby re-finalized at this close — is examined, and each is finalized — but only if every non-`SUPERSEDED` purchase report for that enrollment and quarter rests in `ADJUDICATED` or `SUBMITTED`; a live report still `FLAGGED` holds its accrual open, while `SUPERSEDED` reports, being dead history, are ignored by the guard. Finalization locks `final_rebate_cents` under the final variant of tier resolution: audited figures where an audit has resolved, self-reported figures otherwise, summed across the enrollment's non-`SUPERSEDED` reports for the quarter with the tier resolution of §3.3 run once against the sums. The pass-through split then runs against the locked amount using the member's `commitment_level`. A `PLATINUM` member receives 8,500 basis points — 85 percent — of `final_rebate_cents` while the co-op retains 1,500 basis points; a `STANDARD` member receives 7,500 basis points (75 percent) with the co-op retaining 2,500 basis points; a `BUILDER` member receives 6,500 basis points (65 percent) with the co-op retaining 3,500 basis points. The member's share, `pass_through_cents`, is `final_rebate_cents` multiplied by the member's rate and divided by ten thousand, rounded down once to a whole cent. The co-op's share, `retained_cents`, is the exact complement — `final_rebate_cents` minus `pass_through_cents` — so the two shares always sum precisely back to `final_rebate_cents` with no cent drift; a finalization that would break this identity aborts with `ERR_SPLIT_MISMATCH` (HTTP 500). The accrual moves from `OPEN` to `FINALIZED`, its `version` increments, and the co-op's `pool_reserve_cents` grows by the accrual's `final_rebate_cents`, booking the supplier's rebate obligation into escrow. Every finalization is its own pool event: an accrual re-finalized after a late audit pulled it back books its recomputed `final_rebate_cents` into the pool again, on top of what its earlier finalization booked.

Second, exclusivity recomputation. Every enrollment still `ACTIVE` has its share-of-wallet recalculated against the closing quarter's evidence. The in-program figure is the sum across that enrollment's reports for the closing quarter of `audited_cents` where the report has been audited and `self_report_cents` where it has not. The total-wallet figure is the same kind of sum across every purchase report the member filed for that quarter, across all of the member's enrollments and suppliers. When the total wallet is zero, `exclusivity_share_pct` is 0; otherwise it is the in-program figure multiplied by 100 and divided by the total wallet, rounded down to a whole percentage point. The derived `exclusivity_status` is `NOT_APPLICABLE` when the program's `exclusivity_required` is false; otherwise `COMPLIANT` when the share is at least the program's `exclusivity_threshold_pct` — the threshold is inclusive, so a share exactly equal to the threshold is compliant — and `SHORTFALL` when it falls below. When an enrollment's status flips to `SHORTFALL` on an exclusivity-requiring program, the system automatically opens a clawback case with `trigger_reason` of `EXCLUSIVITY_BREACH`.

Third, holdback release. Every `HoldbackRelease` still in `SCHEDULED` whose `release_quarter_index` is less than or equal to the newly advanced quarter counter comes due. Provided the owning member has not `CHURNED`, the release transitions to `RELEASED`: the pool shrinks by `release_cents`, the member's `lifetime_pass_through_cents` grows by `release_cents`, and the release's `version` increments. If the member has churned, the release is already `FORFEITED` by the churn cascade and no cash moves.

Fourth, the `Coop` entity's own `version` increments, sealing the close.

Once a quarter is closed and its accruals finalized, finance takes over. A `FinanceOfficer` creates the `QuarterlyDistribution` for the current quarter: it arrives in `DRAFT` status with `quarter_index` set to the co-op's current quarter, `coop_id` pointing at the singleton, and every computed total — `gross_rebate_cents`, `total_pass_through_cents`, `total_retained_cents`, `holdback_cents`, `clawback_offset_cents`, `net_disbursed_cents` — at 0. Creation is not limited to one distribution per quarter; each call mints a fresh `DRAFT` distribution stamped with the co-op's then-current quarter. Distributions can be listed and filtered by `coop_id`, `quarter_index`, and `status`.

Calculation turns the draft into numbers. The request must carry `expected_distribution_version` equal to the distribution's current `version`; a stale view is refused with `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412) as described in §2.8. Calculation requires the distribution to be `DRAFT` (else `ERR_INVALID_STATE`) and aggregates every `RebateAccrual` in `FINALIZED` status whose `quarter_index` equals the distribution's quarter. From that set it derives `gross_rebate_cents` as the sum of `final_rebate_cents`, `total_pass_through_cents` as the sum of `pass_through_cents`, and `total_retained_cents` as the sum of `retained_cents`. The holdback comes next, and each included accrual contributes under its own program's `holdback_policy` — a distribution may mix both variants. Pass-through from `FLAT`-policy programs is pooled across the whole distribution and withheld once: the pooled `FLAT` pass-through multiplied by 1,000 basis points — ten percent — and divided by ten thousand, rounded down to a whole cent. Pass-through from `RISK_ADJUSTED`-policy programs is withheld per contributing member: for each member, the member's pass-through contribution from `RISK_ADJUSTED`-policy programs is multiplied by 2,500 basis points when that member's `prior_audit_findings_count` is at least 2, and by 1,000 basis points otherwise — the threshold is inclusive, so exactly two prior material findings triggers the elevated rate — and each per-member product is divided by ten thousand and rounded down to a whole cent. `holdback_cents` is the single `FLAT` withholding plus the sum of the per-member `RISK_ADJUSTED` withholdings. Finally, `clawback_offset_cents` sums the `net_clawback_cents` of every clawback case sitting in `OPEN` or `NOTIFIED` status, and `net_disbursed_cents` is what remains: `total_pass_through_cents` minus `holdback_cents` minus `clawback_offset_cents`. The distribution moves from `DRAFT` to `CALCULATED` and its `version` increments.

Approval and disbursement are deliberately separated. Approval moves a `CALCULATED` distribution to `APPROVED` — any other source state draws `ERR_INVALID_STATE`. Disbursement moves an `APPROVED` distribution to `DISBURSED`, but only if the pool can cover it: when `pool_reserve_cents` falls short of `net_disbursed_cents`, disbursement is refused with `ERR_INSUFFICIENT_POOL` (HTTP 409) and nothing moves. A successful disbursement subtracts `net_disbursed_cents` from `pool_reserve_cents`, adds `total_retained_cents` to `retained_revenue_cents`, transitions every included accrual from `FINALIZED` to `DISTRIBUTED` (each accrual's `version` incrementing), and credits each member's `lifetime_pass_through_cents` by that member's share — the full `pass_through_cents` contribution, not net of the holdback withholding. The disbursement also schedules holdback releases, one per member rather than per accrual: for each contributing member whose withheld amount is greater than zero, a `HoldbackRelease` is created in `SCHEDULED` status against the member, its `source_distribution_id` pointing at the distribution just disbursed, its `release_cents` carrying the withheld cash amount destined for that member, and its `release_quarter_index` set to the current quarter plus the `HOLDBACK_LAG_QUARTERS` lag — the standing holdback lag constant, fixed at 2 quarters, that keeps withheld funds in escrow for a fixed number of quarters before release. The member's withheld amount is computed with per-member floor rounding — the member's `FLAT`-policy pass-through times 1,000 basis points, floored to a cent, plus the member's per-band `RISK_ADJUSTED` withholding computed as above — so when several members contribute to the same `FLAT` pool, the sum of the scheduled releases can fall a few cents short of `holdback_cents`, and that rounding residue simply stays in the pool; a member whose withheld amount floors to zero gets no release row at all. The distribution's `version` increments. Reconciliation, the finance team's final sign-off, moves a `DISBURSED` distribution to the terminal `RECONCILED` state.

Accruals are readable throughout: individually, or as a list filtered by `enrollment_id`, `quarter_index`, and `status`.

### 3.7. Clawbacks, Holdback Forfeiture, and Churn Economics

Clawback cases are the co-op's recovery instrument, and they are always born from events rather than created directly. Three triggers mint a case: churning a member opens one with `trigger_reason` of `CHURN`; resolving an audit with a `MATERIAL` finding against an already-`DISTRIBUTED` accrual opens one with `AUDIT_SHORTFALL`; and a quarter close that flips an exclusivity-requiring enrollment to `SHORTFALL` opens one with `EXCLUSIVITY_BREACH`. In every case the `member_id` is the affected member, `trigger_quarter_index` is stamped with the co-op's `current_quarter_index` at the moment the case is created — so a case minted by the exclusivity cascade during a quarter close records the newly advanced quarter rather than the closing quarter, because the counter advances before the close cascades run (§3.6) — and the amounts are computed by the same waterfall.

The waterfall works as follows, and its order is load-bearing. The compute set is every `RebateAccrual` belonging to the member whose status is `DISTRIBUTED`. First, the gross variant: `gross_clawback_cents` is the sum of `pass_through_cents` across that set — the full member-facing cash the co-op wants back. Second, forfeiture: every `HoldbackRelease` of the member still in `SCHEDULED` transitions to `FORFEITED` (each incrementing its `version`), and their `release_cents` amounts are summed as the forfeited holdback value — value the member will never receive and which therefore offsets the debt. Third, the net variant: `net_clawback_cents` is `gross_clawback_cents` minus the forfeited holdback value, floored at zero so the demand can never be negative. Forfeiture is applied before netting; reversing that order produces a different answer precisely when the forfeited holdbacks exceed the gross. The gross figure is what gets reported to the member; the net figure is the actual cash demand. `recovered_cents` starts at 0, and a `dispute_note` — empty by default — waits for the member's side of the story.

Once open, a case in `OPEN` is advanced by a `CoopAdmin` notifying the member, moving it to `NOTIFIED`. From `NOTIFIED` the member's own `MemberRep` may dispute — supplying a `dispute_note` narrative, subject to the ownership rule that rejects a non-owning caller with `ERR_NOT_RESOURCE_OWNER` and a non-`MemberRep` caller with `ERR_FORBIDDEN` — moving the case to `DISPUTED`. Resolution is available from either `NOTIFIED` or `DISPUTED`, and from either source state it behaves identically: `recovered_cents` is set to `net_clawback_cents`, the recovered amount is added back into `pool_reserve_cents`, the member's `lifetime_clawback_cents` grows by the recovered amount, every accrual in the clawback's compute set transitions from `DISTRIBUTED` to `CLAWED_BACK` (each incrementing its `version`), and the case lands in the terminal `RESOLVED` state with its own `version` incremented. Alternatively, a `CoopAdmin` may waive the case from either `NOTIFIED` or `DISPUTED`: the case lands in the terminal `WAIVED` state and `recovered_cents` remains 0 — nothing is recovered, nothing returns to the pool. Every transition enforces its named source state, failing otherwise with `ERR_INVALID_STATE`.

Cases can be listed and filtered by `member_id`, `status`, and `trigger_reason`; holdback releases can be listed and filtered by `member_id`, `status`, and `source_distribution_id`, so a member's withheld-but-not-yet-released cash is always auditable. The full retroactive chain — an audit resolution that re-opens a finalized accrual, a distribution that must be recalculated against a stale version, a holdback that forfeits into a clawback, a recovery that flows back into the pool — is the deliberate serialization point of the design: every step is versioned, every cascade increments `version` and refreshes `updated_at`, and every cross-entity write follows the state rules above rather than ad-hoc mutation.

## 4. Endpoint Definitions

Endpoints that create a new resource answer 201 Created; all other endpoints — reads, state transitions, and actions — answer 200 OK. Request and response payloads follow the envelope in §2.2, and the workflow narratives in §3 carry the full per-endpoint semantics; the table below is the structural index only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /coop/bootstrap | Initialize the Co-op singleton (one-time) | CoopAdmin |
| GET | /coop | Get the Co-op singleton | CoopAdmin, FinanceOfficer, SupplierRep, MemberRep, ProgramAuditor |
| POST | /coop/_clock/set_current_utc | Set the logical clock (test-driving; default time is 2026-08-01T00:00:00Z) | CoopAdmin |
| POST | /coop/close_quarter | Close the current quarter: advance the counter, finalize accruals, recompute exclusivity, release due holdbacks | CoopAdmin |
| POST | /coop/members | Enroll a new member (PENDING until activated) | CoopAdmin |
| GET | /coop/members/{id} | Get a member | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/members | List members (filterable by status, commitment_level) | CoopAdmin, FinanceOfficer, ProgramAuditor |
| POST | /coop/members/{id}/activate | Activate a PENDING member | CoopAdmin |
| POST | /coop/members/{id}/suspend | Suspend an ACTIVE member (cascades to enrollments) | CoopAdmin |
| POST | /coop/members/{id}/reinstate | Reinstate a SUSPENDED member | CoopAdmin |
| POST | /coop/members/{id}/churn | Churn a member (cascades enrollment exit, holdback forfeiture, clawback creation) | CoopAdmin |
| POST | /coop/suppliers | Create a supplier in PROSPECT status | CoopAdmin |
| GET | /coop/suppliers/{id} | Get a supplier | CoopAdmin, SupplierRep, FinanceOfficer, ProgramAuditor |
| GET | /coop/suppliers | List suppliers (filterable by status) | CoopAdmin, FinanceOfficer, ProgramAuditor, SupplierRep |
| POST | /coop/suppliers/{id}/onboard | Onboard a PROSPECT supplier | CoopAdmin |
| POST | /coop/suppliers/{id}/deactivate | Deactivate an ONBOARDED supplier (requires no active programs) | CoopAdmin |
| POST | /coop/suppliers/{id}/supplier-programs | Create a new supplier program in DRAFT status | SupplierRep, CoopAdmin |
| GET | /coop/supplier-programs/{id} | Get a supplier program | CoopAdmin, SupplierRep, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/supplier-programs | List supplier programs (filterable by supplier_id, status) | CoopAdmin, SupplierRep, FinanceOfficer, ProgramAuditor, MemberRep |
| PUT | /coop/supplier-programs/{id} | Amend a program's terms (renegotiation; OCC-guarded; increments negotiation_round) | SupplierRep |
| POST | /coop/supplier-programs/{id}/open | Open a DRAFT program for enrollment | SupplierRep |
| POST | /coop/supplier-programs/{id}/close_to_new | Stop accepting new enrollments (existing members continue) | SupplierRep |
| POST | /coop/supplier-programs/{id}/reopen | Reopen a CLOSED_TO_NEW program | SupplierRep |
| POST | /coop/supplier-programs/{id}/terminate | Terminate a program (requires no ACTIVE/SUSPENDED enrollments) | SupplierRep |
| POST | /coop/enrollments | Enroll a member in a supplier program | CoopAdmin, MemberRep |
| GET | /coop/enrollments/{id} | Get an enrollment | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep, SupplierRep |
| GET | /coop/enrollments | List enrollments (filterable by member_id, program_id, status) | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep, SupplierRep |
| POST | /coop/enrollments/{id}/exit | Voluntarily exit an ACTIVE enrollment (no clawback) | CoopAdmin, MemberRep |
| POST | /coop/enrollments/{id}/purchase-reports | Submit a member's self-reported purchase volume for the current quarter | MemberRep, CoopAdmin |
| GET | /coop/purchase-reports/{id} | Get a purchase report | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/enrollments/{id}/purchase-reports | List purchase reports for an enrollment | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/purchase-reports | List purchase reports (flat filterable list for FK reverse-reachability) | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/purchase-reports/{id}/volume-audits | List volume audits targeting a given purchase report | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| POST | /coop/purchase-reports/{id}/flag | Flag a SUBMITTED report for audit review | ProgramAuditor |
| POST | /coop/purchase-reports/{id}/revise | Member revises a FLAGGED report — creates a new SUBMITTED row; the old row becomes SUPERSEDED | MemberRep |
| POST | /coop/volume-audits | Open a volume audit against a SUBMITTED purchase report | ProgramAuditor |
| GET | /coop/volume-audits/{id} | Get a volume audit | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/volume-audits | List volume audits (filterable) | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| POST | /coop/volume-audits/{id}/begin_fieldwork | Move an audit from OPEN to FIELDWORK | ProgramAuditor |
| POST | /coop/volume-audits/{id}/issue_findings | Issue findings — FIELDWORK to FINDINGS_ISSUED | ProgramAuditor |
| POST | /coop/volume-audits/{id}/accept_findings | Member accepts findings — FINDINGS_ISSUED to ACCEPTED | MemberRep |
| POST | /coop/volume-audits/{id}/appeal | Member appeals findings — FINDINGS_ISSUED to APPEALED | MemberRep |
| POST | /coop/volume-audits/{id}/reopen_fieldwork | Reopen fieldwork after an appeal — APPEALED to FIELDWORK | ProgramAuditor |
| POST | /coop/volume-audits/{id}/resolve | Resolve an ACCEPTED audit; attested values retroactively mutate the downstream accrual | ProgramAuditor |
| GET | /coop/rebate-accruals/{id} | Get a rebate accrual | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/rebate-accruals | List rebate accruals (filterable) | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| POST | /coop/distributions | Create a quarterly distribution for the current quarter (DRAFT) | FinanceOfficer |
| GET | /coop/distributions/{id} | Get a quarterly distribution | CoopAdmin, FinanceOfficer, ProgramAuditor, MemberRep |
| GET | /coop/distributions | List quarterly distributions (filterable) | CoopAdmin, FinanceOfficer, ProgramAuditor |
| POST | /coop/distributions/{id}/calculate | Calculate the distribution totals (OCC-guarded) | FinanceOfficer |
| POST | /coop/distributions/{id}/approve | Approve a CALCULATED distribution | FinanceOfficer |
| POST | /coop/distributions/{id}/disburse | Disburse an APPROVED distribution (requires sufficient pool) | FinanceOfficer |
| POST | /coop/distributions/{id}/reconcile | Reconcile a DISBURSED distribution | FinanceOfficer |
| GET | /coop/clawback-cases/{id} | Get a clawback case | CoopAdmin, FinanceOfficer, MemberRep |
| GET | /coop/clawback-cases | List clawback cases (filterable) | CoopAdmin, FinanceOfficer, MemberRep |
| POST | /coop/clawback-cases/{id}/notify | Notify the member of a clawback | CoopAdmin |
| POST | /coop/clawback-cases/{id}/dispute | Member disputes the clawback | MemberRep |
| POST | /coop/clawback-cases/{id}/resolve | Resolve a clawback — recovers the net amount | CoopAdmin |
| POST | /coop/clawback-cases/{id}/waive | Waive a clawback (no recovery) | CoopAdmin |
| GET | /coop/holdback-releases/{id} | Get a holdback release | CoopAdmin, FinanceOfficer, MemberRep |
| GET | /coop/holdback-releases | List holdback releases (filterable) | CoopAdmin, FinanceOfficer, MemberRep |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_INSUFFICIENT_POOL | 409 |
| ERR_QUARTER_MISMATCH | 409 |
| ERR_FUTURE_QUARTER | 409 |
| ERR_SPLIT_MISMATCH | 500 |
| ERR_INVALID_TIER_SCHEDULE | 422 |
| ERR_INVALID_EXCLUSIVITY | 422 |
| ERR_DUPLICATE_PROGRAM_CODE | 409 |
| ERR_SUPPLIER_NOT_ONBOARDED | 409 |
| ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS | 409 |
| ERR_PROGRAM_NOT_OPEN | 409 |
| ERR_PROGRAM_HAS_ENROLLMENTS | 409 |
| ERR_MEMBER_NOT_ACTIVE | 409 |
| ERR_OPEN_CLAWBACK | 409 |
| ERR_STALE_PROGRAM_VERSION | 412 |
| ERR_STALE_DISTRIBUTION_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
