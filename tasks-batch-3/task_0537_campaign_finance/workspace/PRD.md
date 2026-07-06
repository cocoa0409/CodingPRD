# Campaign Finance & Lobbyist Disclosure API — Product Requirements Document

## 1. Introduction

Election-integrity agencies are asked to reconcile two very different disclosure obligations under one roof: the money that flows into and out of political committees, and the money that lobbying firms spend influencing legislation on behalf of paying clients. Historically these have lived in separate systems with incompatible deadline, penalty, and public-search semantics, forcing auditors to cross-check spreadsheets by hand and leaving the public with fragmented visibility.

This document specifies a single disclosure platform that governs both trees. On the campaign-finance side it tracks committee registration, contribution intake with source-prohibition and per-donor limit enforcement, disbursements, periodic report filing against agency-defined windows, and a tiered late-filing penalty regime that flows through to each committee's running solvency. On the lobbying side it tracks registrant and client registration, per-period activity disclosure, and the certification of spend once a period closes. Both trees share the same reporting-period, deadline, and lateness machinery, the same role-and-ownership model, and the same public-search disclosure surface. The platform is authoritative and consistent: every derived total is recomputed immediately as its inputs change, and a test-drivable logical clock — never wall-clock time — determines whether any filing is late.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across both the campaign-finance and lobbying disclosure trees. The API is mounted under `/disclosure`.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operating capacity. If either header is missing, or `X-User-Role` is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Treasurer`, `RegulatorAuditor`, `LobbyRegistrant`, and `PublicViewer`.

- When `X-User-Role` is `Treasurer`, `X-User-ID` is the `id` of the acting `Committee`; ownership checks on any resource that references a `Committee` compare that resource's `committee_id` to `X-User-ID`. A treasurer owns a committee's entire finance surface — its contributions, expenditures, and reports. Committee registration itself is performed by a `Treasurer` but carries no ownership check, since the committee does not yet exist at that point.
- When `X-User-Role` is `LobbyRegistrant`, `X-User-ID` is the `id` of the acting `LobbyingRegistrant`; ownership checks on any resource that references a registrant compare that resource's `registrant_id` to `X-User-ID`. A registrant owns its clients and its lobbying activities. Registrant registration itself carries no ownership check.
- When `X-User-Role` is `RegulatorAuditor`, `X-User-ID` is an opaque agency-operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`. The auditor is the agency operator responsible for approvals, compliance void/flag/clear actions, reporting-period lifecycle, audits, penalty waivers, and the logical clock.
- When `X-User-Role` is `PublicViewer`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity and is never compared to any resource. Public viewers may only read.

For owner-scoped mutations — contribution, expenditure, and report writes on the campaign-finance side, and client and activity writes on the lobbying side — an authenticated principal of the correct role who is nevertheless not the owner of the target resource is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403). Every read (GET) endpoint is available to all four roles.

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

List endpoints are paginated through two query parameters. `limit` is the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items skipped from the front of the result set and defaults to 0.

Unless a specific endpoint says otherwise, every list is sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent mutation, and `version` is an integer that starts at its initial value and increments by one on every mutation of the resource. Derived-total recomputations count as mutations: whenever a committee's or registrant's rolling totals change, that entity's `updated_at` is refreshed and its `version` is incremented.

One entity is exempt from part of this convention. An `Expenditure` is immutable after creation and therefore carries only `id` and `created_at`; it has no `updated_at` and no `version`. Every other resource — `Committee`, `Contribution`, `ReportingPeriod`, `Report`, `LobbyingRegistrant`, `Client`, `LobbyingReportingPeriod`, and `LobbyingActivity` — carries the full set including `updated_at` and `version`.

### 2.5. The Logical Clock and Filing Deadlines

All deadline and lateness determinations read a server-side **logical UTC clock**, never wall-clock time. On startup the clock reads `2026-05-01T00:00:00Z`, and it never falls back to real time. An agency operator advances it by supplying a target instant `to_iso8601`; the clock is then pinned to that value until the next advance.

A reporting period declares a `filing_deadline`, the instant strictly after which a filing for that period is considered late. When a report is filed, the moment of filing is stamped as `filed_at` from the current logical clock. Lateness is a strict comparison: a report is late only when its `filed_at` is strictly later than the covered period's `filing_deadline`; filing exactly at the deadline is on time. The whole-days-late count is the difference between `filed_at` and `filing_deadline` divided into 24-hour days and rounded up to the next whole day (any positive fractional day counts as a full day).

### 2.6. Monetary Values and Precision

All monetary quantities are stored and returned as integer cents. Amounts are never carried as fractional cents and there is no decimal rounding of stored totals — sums of integer cents remain integers.

Rounding enters only where a rate is applied. Public-match amounts multiply an integer cent value by a matching rate; each such product is rounded half up to a whole number of cents. Where that rounding is applied per line item versus applied to a sum, the order is significant and is specified precisely in §3.5.

### 2.7. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the earliest failing check determines the returned error. The order is:

1. **Authentication** — `X-User-Role` and `X-User-ID` are present and the role is one of the four known roles; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted to perform this operation per §2.1 and §4; otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource named by a path identifier exists, validated left-to-right; the first missing one yields its own not-found error (404), such as `ERR_COMMITTEE_NOT_FOUND` or `ERR_REGISTRANT_NOT_FOUND`.
4. **Ownership** — an entity-backed actor owns the target resource; otherwise `ERR_FORBIDDEN_OWNER` (403).
5. **Body validation** — required body fields are present, correctly typed, and any enum value is a valid member; otherwise `ERR_VALIDATION` (422).
6. **Amount validity** — a monetary `amount_cents` on a contribution, expenditure, or activity is strictly greater than zero; otherwise `ERR_INVALID_AMOUNT` (422).
7. **Optimistic concurrency** — where an operation is OCC-guarded, the supplied version matches the parent's current `version`; otherwise `ERR_STALE_VERSION` (412).
8. **Target-state guard** — the target resource's own status permits the requested transition; otherwise a state-conflict error (409) such as `ERR_REPORT_NOT_DRAFT` or `ERR_CONTRIBUTION_NOT_RECORDED`.
9. **Cross-entity state** — related entities are in the required state (for example, the committee is `ACTIVE` for a contribution/expenditure/report create; the client and registrant are `ACTIVE` for an activity create); otherwise a 409 such as `ERR_COMMITTEE_NOT_ACTIVE`, `ERR_CLIENT_NOT_ACTIVE`, or `ERR_REGISTRANT_NOT_ACTIVE`.
10. **Filing window** — filing requires the covered period to be `CLOSED`; otherwise `ERR_PERIOD_NOT_CLOSED` (409).
11. **Period overlap** — a new reporting period does not conflict with an existing one in its scope; otherwise `ERR_PERIOD_OVERLAP` (409).
12. **Activity overlap** — a new activity does not collide in date with another recorded activity for the same registrant-and-client pair; otherwise `ERR_ACTIVITY_OVERLAP` (409).
13. **Source prohibition** — the contributor source is not prohibited for the committee type; otherwise `ERR_PROHIBITED_SOURCE` (409).
14. **Contribution limit** — the per-contributor per-cycle aggregate would not exceed the applicable limit; otherwise `ERR_CONTRIBUTION_LIMIT_EXCEEDED` (409).

An implication worth calling out: for a contribution intake, both the source-prohibition check (step 13) and the limit check (step 14) run only after existence, ownership, body, amount, and committee-active checks have all passed, and source prohibition is decided before the limit aggregate. A source that is outright prohibited is rejected with `ERR_PROHIBITED_SOURCE` even if, numerically, the amount would also be within a limit.

### 2.8. Optimistic Concurrency Control

Creating a report for a committee is optimistic-concurrency guarded on the parent committee. The create request must carry `expected_committee_version`, a non-optional field carrying the client's last observed `version` of the target `Committee`. If that value does not equal the committee's current `version` — because another writer has advanced the committee since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects the invariant that a report create supersedes the prior draft for its period: a stale view means the writer's assumption about the committee's report set no longer holds, so the write must be refused rather than allowed to overwrite work it never observed. No other endpoint takes a version field; only report creation is OCC-guarded.

### 2.9. Derived Committee Ledger, Cascades, and Solvency

Each `Committee` maintains four derived totals that are never supplied by clients and are recomputed immediately whenever their inputs change. `total_receipts_cents` is the sum of `amount_cents` over the committee's contributions whose `settlement_status` is either `RECORDED` or `DEPOSITED` (refunded and voided contributions are excluded); it is recomputed on every contribution mutation. `total_disbursements_cents` is the sum of `amount_cents` over the committee's expenditures and is recomputed when an expenditure is created. `total_penalties_cents` is the sum of `penalty_amount_cents` over the committee's reports whose `penalty_status` is `ASSESSED`; it is recomputed when a report is filed or a penalty is waived.

From those three, the committee's `cash_on_hand_cents` is evaluated in a pinned order: first `total_receipts_cents`, then `total_disbursements_cents`, then `total_penalties_cents`, and finally `cash_on_hand_cents` as `total_receipts_cents` minus `total_disbursements_cents` minus `total_penalties_cents`. This fixed order is what breaks the apparent circularity between receipts and penalties — penalties are keyed off a report's own receipts tier, not off cash on hand, so the subtraction is well-defined. The committee's `solvency_status` is then derived from the result: it is `DEFICIT` when `cash_on_hand_cents` is strictly below zero, and `SOLVENT` otherwise (a value of exactly zero is `SOLVENT`).

Several operations cascade through this chain. When a contribution is refunded or voided, receipts are recomputed downward, then cash on hand is recomputed from the new receipts, then solvency is recomputed from the new cash on hand, and the committee's `version` is incremented. When a report is filed late, the newly assessed penalty flows into total penalties, then into cash on hand, then into solvency, again bumping `version`. Every such reconciliation is a mutation of the committee that refreshes its `updated_at`.

The lobbying tree has an analogous pair of registrant totals; see §3.7.

### 2.10. Nested Resource Retrieval

Many paths embed more than one identifier — for example a client or activity nested under a registrant, or reports nested under a committee or a period. The system validates path identifiers left-to-right and rejects the request at the first one that does not resolve, returning that resource's not-found error before looking at anything to its right. A request for activities under a non-existent registrant fails with `ERR_REGISTRANT_NOT_FOUND` before any activity lookup is attempted. Each resource type has its own not-found error, returned when its identifier is the first unresolved one in the path: `ERR_COMMITTEE_NOT_FOUND`, `ERR_CONTRIBUTION_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and `ERR_ACTIVITY_NOT_FOUND` among them. Body-referenced identifiers are validated in the same spirit: a create that names a `period_id` or `client_id` that does not exist is rejected with the corresponding not-found error (`ERR_PERIOD_NOT_FOUND`, `ERR_LOBBYING_PERIOD_NOT_FOUND`, or `ERR_CLIENT_NOT_FOUND`).

### 2.11. Reporting Period Scheduling and Overlap

The agency defines the windows against which filings and lobbying disclosures are measured, and it guarantees those windows do not conflict within their scope. The two period types differ in their interval semantics, and the difference is deliberate.

A campaign-finance reporting period spans a **half-open** interval from `period_start` (inclusive) up to but not including `period_end`. Overlap uniqueness is scoped to the combination of `jurisdiction` and `election_cycle`: two periods conflict when their half-open intervals share any instant. Because the interval is half-open, one period ending exactly where the next begins do **not** overlap. A conflicting create is rejected with `ERR_PERIOD_OVERLAP`.

A lobbying reporting period spans a **closed** interval from `period_start` through `period_end`, both endpoints inclusive, and its overlap scope is `jurisdiction` alone. Under closed-interval semantics, adjacency counts as a conflict: a period ending exactly where the next begins overlaps at that shared endpoint. A conflicting create is likewise rejected with `ERR_PERIOD_OVERLAP`.

## 3. Business Logic & Workflows

### 3.1. Committee Registration and Lifecycle

A `Treasurer` registers a committee by supplying its `name`, its `committee_type` — one of `CANDIDATE`, `PAC`, or `PARTY` — its `election_cycle` label (for example `2026`, the key on which per-cycle contribution aggregates are grouped), its filing `jurisdiction` code, and the `treasurer_name` of the responsible officer of record. A newly registered committee begins in `PENDING` with all four derived totals zeroed and `solvency_status` at `SOLVENT`.

The committee then moves through a small lifecycle. Agency approval advances a committee from `PENDING` to `ACTIVE`; this is permitted only while the committee is `PENDING`, and an attempt against any other state is rejected with `ERR_COMMITTEE_NOT_PENDING`. An agency operator may suspend an active committee, moving it from `ACTIVE` to `SUSPENDED`; this requires the committee to be `ACTIVE` and is otherwise rejected with `ERR_COMMITTEE_NOT_ACTIVE`. The owning treasurer may terminate their own committee, moving it to the terminal `TERMINATED` state from either `ACTIVE` or `SUSPENDED`; a committee that is `PENDING` or already `TERMINATED` cannot be terminated and the transition is refused as a state conflict. Every one of these transitions increments the committee's `version`.

Only an `ACTIVE` committee may accept new contributions, expenditures, or reports; when the committee is in any other state those creates are refused with `ERR_COMMITTEE_NOT_ACTIVE`.

### 3.2. Recording Contributions: Prohibited Sources and Per-Cycle Limits

The owning treasurer records an incoming contribution against a committee by supplying the stable `contributor_ref` (the identity key the per-cycle limit aggregate is grouped on), the display `contributor_name`, the `contributor_type`, the `amount_cents`, and the `contribution_date` on which the money was received. The recipient committee is identified by `committee_id` from the path. A contribution is created with `settlement_status` at `RECORDED` and `review_status` at `UNREVIEWED`, and its creation recomputes the committee's receipts, cash on hand, and solvency and bumps the committee's `version`.

`contributor_type` is one of `INDIVIDUAL`, `PAC`, `PARTY`, `CORPORATION`, `UNION`, or `FOREIGN_NATIONAL`. The amount must be strictly positive; a zero or negative `amount_cents` is rejected with `ERR_INVALID_AMOUNT`.

Two business gates then apply, in this order. First, **source prohibition**: certain source-and-committee combinations are simply not allowed to give, independent of amount. A `FOREIGN_NATIONAL` may not contribute to any committee type. A `CORPORATION` may contribute only to a `PAC` committee — never to a `CANDIDATE` or `PARTY` committee. A `UNION` likewise may contribute only to a `PAC` committee. Any of these prohibited combinations is rejected with `ERR_PROHIBITED_SOURCE`.

Second, if the source is permitted, the **per-contributor per-cycle limit** is enforced. The system sums `amount_cents` over the committee's existing contributions from the same `contributor_ref` whose `settlement_status` is `RECORDED` or `DEPOSITED` (refunded and voided contributions do not count), adds the amount of the incoming contribution, and compares the resulting aggregate against the applicable limit. The comparison is strict: the contribution is rejected with `ERR_CONTRIBUTION_LIMIT_EXCEEDED` only when the new aggregate is strictly greater than the limit; an aggregate exactly equal to the limit is allowed.

The limit is selected from the contributor type and committee type as follows (all figures in integer cents):

- An `INDIVIDUAL` may give up to 330000 to a `CANDIDATE` committee, 500000 to a `PAC`, and 4130000 to a `PARTY`.
- A `PAC` source may give up to 500000 to a `CANDIDATE`, 500000 to a `PAC`, and 1500000 to a `PARTY`.
- A `PARTY` source may give up to 500000 to a `CANDIDATE` and 500000 to a `PAC`; its limit toward another `PARTY` committee is 0, so any positive contribution from a `PARTY` source to a `PARTY` committee necessarily exceeds the limit and is rejected with `ERR_CONTRIBUTION_LIMIT_EXCEEDED` (note this is a limit outcome, not a prohibited-source outcome).
- A `CORPORATION` and a `UNION` may each give up to 500000, but only to a `PAC` committee (all their other combinations are prohibited sources, handled above).

At creation the system also computes each contribution's `matchable_amount_cents`, the portion eligible for public matching. For an `INDIVIDUAL` source this is the smaller of the contribution's `amount_cents` and a matchable cap of 20000 cents; for every other contributor type it is 0. This per-line matchable figure feeds the report matching-funds calculation in §3.5.

### 3.3. Contribution Settlement and Compliance Review

Each contribution carries two independent status dimensions on the same row, and a transition on one never disturbs the other. The **settlement** dimension tracks the money; the **review** dimension tracks compliance scrutiny.

On the settlement side, the owning treasurer deposits a recorded contribution, moving `settlement_status` from `RECORDED` to `DEPOSITED`; this requires the contribution to be `RECORDED` and is otherwise rejected with `ERR_CONTRIBUTION_NOT_RECORDED`. A deposit leaves the committee's `total_receipts_cents` unchanged, because both `RECORDED` and `DEPOSITED` contributions already count toward receipts, but it still increments the committee's `version`. The treasurer may refund a deposited contribution, moving it from `DEPOSITED` to the terminal `REFUNDED`; this requires the contribution to be `DEPOSITED` and is otherwise rejected with `ERR_CONTRIBUTION_NOT_DEPOSITED`. A refund excludes the contribution from receipts, so the committee's `total_receipts_cents` is recomputed downward, then `cash_on_hand_cents` from the new receipts, then `solvency_status` from the new cash on hand, and the committee's `version` is incremented.

An agency auditor may void a contribution for compliance reasons, moving `settlement_status` to the terminal `VOIDED` from either `RECORDED` or `DEPOSITED`; a contribution in any other settlement state cannot be voided and the request is rejected with `ERR_CONTRIBUTION_NOT_VOIDABLE`. A void, like a refund, drops the contribution from receipts and cascades the same way: receipts recomputed downward, then cash on hand, then solvency, then a `version` increment on the committee.

On the review side, an agency auditor flags an unreviewed contribution, moving `review_status` from `UNREVIEWED` to `FLAGGED`, and later clears it, moving `review_status` from `FLAGGED` to `CLEARED`. Flagging requires the review status to be `UNREVIEWED` and clearing requires it to be `FLAGGED`; a request that does not meet its precondition is rejected with `ERR_CONTRIBUTION_REVIEW_INVALID`. Neither flag nor clear touches the settlement dimension, but each is a committee-affecting mutation and increments the committee's `version`.

### 3.4. Expenditures

The owning treasurer records a disbursement against an active committee by supplying the `payee_name`, the `amount_cents`, the `expenditure_date`, and the stated `purpose`. The spending committee is identified by `committee_id` from the path. The amount must be strictly positive or the create is rejected with `ERR_INVALID_AMOUNT`. Creating an expenditure recomputes the committee's `total_disbursements_cents`, then its `cash_on_hand_cents`, then its `solvency_status`, and increments the committee's `version`. An expenditure is immutable once created and has no lifecycle transitions of its own.

### 3.5. Reporting Periods, Draft Reports, and Filing

An agency operator defines a campaign-finance reporting period by supplying its `jurisdiction`, `election_cycle`, a human `period_label` such as `Q1-2026`, the `period_start` and `period_end` bounding its half-open window, and the `filing_deadline`. The period is created `OPEN`. When the agency later closes it, the period moves from `OPEN` to `CLOSED`; closing requires the period to be `OPEN` and is otherwise rejected with `ERR_PERIOD_NOT_OPEN`, and it increments the period's `version`. Filing is only possible against a closed period.

A treasurer creates a draft report for one of their committees by naming the `period_id` it covers and supplying `expected_committee_version` for the optimistic-concurrency check of §2.8. The committee is identified by `committee_id` from the path. Creating the report supersedes any prior `DRAFT` report for that same committee-and-period pairing — the earlier draft moves to the terminal `SUPERSEDED` state — and produces a fresh report in `DRAFT` with `amendment_seq` 0, `supersedes_report_id` null, and its totals computed in the **provisional** variant. The committee's `version` is incremented.

A report's `total_receipts_cents` is the sum of `amount_cents` over the committee's contributions whose `contribution_date` falls in the period's half-open window — at or after `period_start` and strictly before `period_end` — filtered by settlement status. The **provisional** variant, used while the report is a draft, counts contributions whose `settlement_status` is `RECORDED` or `DEPOSITED`. The **final** variant, computed when the report is filed, counts only `DEPOSITED` contributions; because recorded-but-not-yet-deposited money drops out, the final total is always less than or equal to the provisional total. The report's `total_disbursements_cents` is the sum of `amount_cents` over the committee's expenditures whose `expenditure_date` falls in the same half-open window.

The report's `matching_funds_cents` is the public-match total, computed with a pinned rounding order. The eligible line items are the in-window contributions with a positive `matchable_amount_cents`, under the same settlement filter as the receipts variant in force (draft: `RECORDED` or `DEPOSITED`; filed: `DEPOSITED` only). For each eligible line item, its `matchable_amount_cents` is multiplied by the one-third matching rate (0.3333333333333333) and that product is rounded half up to a whole number of cents; the rounded per-line results are then summed. The rounding is applied per line item and then summed — never by summing the matchable amounts first and rounding once; that sum-then-round order is explicitly rejected.

To file, the treasurer transitions the report from `DRAFT` to `FILED`. Filing requires the report to be a draft (otherwise `ERR_REPORT_NOT_DRAFT`), the acting treasurer to own the committee, and the covered period to be `CLOSED` (otherwise `ERR_PERIOD_NOT_CLOSED`). On filing, `total_receipts_cents` and `matching_funds_cents` are recomputed in their final variants, `filed_at` is stamped from the current logical clock, and lateness is pinned: `is_late` becomes true exactly when `filed_at` is strictly after the period's `filing_deadline`, and `days_late` becomes the deadline-to-filing gap divided into 24-hour days and rounded up to a whole day when late, or 0 when on time. When the filing is late, the late-filing penalty of §3.6 is assessed and cascades into committee solvency. Filing increments the committee's `version`.

### 3.6. Late-Filing Penalties, Audits, Amendments, and Waivers

When a filed report is late, the system assesses a tiered penalty and pins it on the report as `penalty_amount_cents`, setting `penalty_status` from `NONE` to `ASSESSED`. The penalty depends on three interacting inputs: the report's final `total_receipts_cents`, which selects a size tier; a base fee; and a per-day rate multiplied by `days_late`. The size tier is `SMALL` when final receipts are at most 500000 cents, `MEDIUM` when they are above that but at most 5000000 cents, and `LARGE` when they exceed 5000000 cents. The per-day rate is 1000 cents for a `SMALL` report, 5000 cents for a `MEDIUM` report, and 20000 cents for a `LARGE` report. The raw penalty is a base fee of 2500 cents plus the tier's per-day rate multiplied by `days_late`. The final `penalty_amount_cents` is the smaller of that raw amount and a ceiling of 1000000 cents. When a report is not late, `penalty_amount_cents` stays 0 and `penalty_status` stays `NONE`.

An assessed penalty immediately flows through the committee: `total_penalties_cents` is recomputed to include this report's penalty, then `cash_on_hand_cents` is recomputed from the new penalties total, then `solvency_status` is recomputed from the new cash on hand — this is the second half of the filing cascade in §2.9.

A filed report can enter an audit loop. An agency auditor opens an audit, moving the report from `FILED` to `UNDER_AUDIT`; this requires the report to be `FILED` and is otherwise rejected with `ERR_REPORT_NOT_FILED`. The auditor closes the audit with no finding, moving it from `UNDER_AUDIT` back to `FILED`; this requires the report to be `UNDER_AUDIT` and is otherwise rejected with `ERR_REPORT_NOT_UNDER_AUDIT`. This loop may repeat.

A treasurer amends a filed report. Amending requires the report to be `FILED` (otherwise `ERR_REPORT_NOT_FILED`) and the acting treasurer to own the committee. Amending moves the old report to the terminal `SUPERSEDED` state and creates a new report in `DRAFT` for the same committee and period, with its `supersedes_report_id` pointing at the old report's `id` and its `amendment_seq` set to one greater than the old report's `amendment_seq`, forming an amendment chain. The committee's `version` is incremented. The amendment produced this way is discoverable through the superseded report's revisions listing.

An agency auditor may waive an assessed penalty, moving the report's `penalty_status` from `ASSESSED` to `WAIVED`; this requires the penalty to be currently `ASSESSED` and is otherwise rejected with `ERR_PENALTY_NOT_ASSESSED`. A waiver drops this report from the committee's assessed-penalty sum, so `total_penalties_cents` is recomputed, then `cash_on_hand_cents`, then `solvency_status`, and the committee's `version` is incremented.

### 3.7. Lobbying Registrants, Clients, and Activities

A `LobbyRegistrant` registers a lobbying firm by supplying its `name`, a `registrant_contact` of record, and its `jurisdiction`. A registrant is created `ACTIVE` with both spend totals zeroed. The owning registrant may terminate its own registration, moving it from `ACTIVE` to the terminal `TERMINATED`; this requires the registrant to be `ACTIVE` and is otherwise rejected with `ERR_REGISTRANT_NOT_ACTIVE`, and it increments the registrant's `version`.

The owning registrant adds a client under its registration by supplying the `client_name`; the retaining registrant is identified by `registrant_id` from the path. A client is created `ACTIVE`. The registrant may deactivate a client, moving it from `ACTIVE` to the terminal `INACTIVE`; deactivation requires the client to be `ACTIVE` and increments the client's `version`.

The owning registrant records a lobbying activity by supplying the `client_id` the activity was performed for, the `period_id` of the lobbying reporting period it is disclosed under, the `lobbyist_name` of the individual who performed it, the `subject` lobbied, the `amount_cents` of spend attributed to it, and the `activity_date`. The reporting registrant is identified by `registrant_id` from the path. The spend amount must be strictly positive or the create is rejected with `ERR_INVALID_AMOUNT`. Recording an activity requires both the client and the registrant to be `ACTIVE`; a non-active client is rejected with `ERR_CLIENT_NOT_ACTIVE` and a non-active registrant with `ERR_REGISTRANT_NOT_ACTIVE`. In addition, the new activity's `activity_date` must not fall inside the occupied window of another `RECORDED` activity for the same registrant-and-client pair; overlap is evaluated at day granularity on a closed interval, so an activity on a day already occupied by another recorded activity for that same pair is rejected with `ERR_ACTIVITY_OVERLAP`. A newly recorded activity is created in `RECORDED` status, and its creation recomputes the registrant's spend totals and increments the registrant's `version`.

A registrant maintains two spend totals. `total_committed_spend_cents` is the sum of `amount_cents` over the registrant's `RECORDED` activities across all periods regardless of period status — the provisional view. `total_certified_spend_cents` is the sum of `amount_cents` over the registrant's `RECORDED` activities whose lobbying period is `CLOSED` — the certified view; because it restricts to closed periods, the certified total is always less than or equal to the committed total.

An agency operator defines a lobbying reporting period by supplying its `jurisdiction`, a `period_label` such as `H1-2026`, the `period_start` and `period_end` bounding its closed interval, and the `filing_deadline`. It is created `OPEN`. Closing a lobbying period moves it from `OPEN` to `CLOSED`; this requires the period to be `OPEN` (otherwise `ERR_PERIOD_NOT_OPEN`) and increments the period's `version`. Closing also certifies spend: every registrant that has `RECORDED` activities in the just-closed period has its `total_certified_spend_cents` recomputed, since those activities are now in a closed period.

The owning registrant may void a recorded activity, moving it from `RECORDED` to the terminal `VOIDED`; this requires the activity to be `RECORDED` and is otherwise rejected with `ERR_ACTIVITY_NOT_VOIDABLE`. Voiding an activity recomputes the registrant's `total_committed_spend_cents` downward, and also recomputes `total_certified_spend_cents` downward when the voided activity's period was `CLOSED`, then increments the registrant's `version`.

### 3.8. Public Disclosure Search

All four roles, including read-only public viewers, may browse the disclosure surface. Committees can be listed and filtered by `status`, `committee_type`, and `jurisdiction`. A committee's contributions can be listed and filtered by `settlement_status` and `review_status`, and its expenditures and reports can be listed as well; report listings accept `status` and `period_id` filters, and the reports covering a given period can be listed with an optional `committee_id` filter. A superseded report's amendment chain is browsable through its revisions listing.

A cross-committee contribution search accepts filters for `committee_id`, `contributor_ref`, `contributor_type`, a `min_amount_cents` floor, and `settlement_status`. On the lobbying side, a registrant's clients (filterable by `status`) and activities (filterable by `client_id`, `period_id`, and `status`) can be listed, as can a client's activities and the activities disclosed under a lobbying period (filterable by `registrant_id`). A cross-registrant activity search accepts filters for `registrant_id`, `client_id`, a `min_amount_cents` floor, and `status`. All of these lists honor the pagination and sort rules of §2.3.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; state transitions and other modifications to existing resources return `200 OK`. The logical-clock adjustment is an operational command and returns `200 OK`. Each endpoint's request payload and side effects are described in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/disclosure/_clock/set_current_utc` | Set the server's logical UTC clock | RegulatorAuditor |
| POST | `/disclosure/committees` | Register a committee (starts PENDING) | Treasurer |
| GET | `/disclosure/committees` | List/search committees | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/committees/{id}` | Fetch a committee | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/committees/{id}/approve` | Approve a committee (PENDING → ACTIVE) | RegulatorAuditor |
| POST | `/disclosure/committees/{id}/suspend` | Suspend a committee (ACTIVE → SUSPENDED) | RegulatorAuditor |
| POST | `/disclosure/committees/{id}/terminate` | Terminate own committee | Treasurer |
| POST | `/disclosure/committees/{id}/contributions` | Record a contribution | Treasurer |
| GET | `/disclosure/committees/{id}/contributions` | List a committee's contributions | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/contributions` | Public-search contributions | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/contributions/{id}` | Fetch a contribution | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/contributions/{id}/deposit` | Deposit a contribution (RECORDED → DEPOSITED) | Treasurer |
| POST | `/disclosure/contributions/{id}/refund` | Refund a contribution (DEPOSITED → REFUNDED) | Treasurer |
| POST | `/disclosure/contributions/{id}/void` | Void a contribution | RegulatorAuditor |
| POST | `/disclosure/contributions/{id}/flag` | Flag a contribution for review | RegulatorAuditor |
| POST | `/disclosure/contributions/{id}/clear` | Clear a flagged contribution | RegulatorAuditor |
| POST | `/disclosure/committees/{id}/expenditures` | Record an expenditure | Treasurer |
| GET | `/disclosure/committees/{id}/expenditures` | List a committee's expenditures | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/reporting-periods` | Create a campaign-finance reporting period | RegulatorAuditor |
| GET | `/disclosure/reporting-periods/{id}` | Fetch a reporting period | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/reporting-periods/{id}/close` | Close a reporting period (OPEN → CLOSED) | RegulatorAuditor |
| POST | `/disclosure/committees/{id}/reports` | Create/refresh a DRAFT report (OCC-guarded) | Treasurer |
| GET | `/disclosure/committees/{id}/reports` | List a committee's reports | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/reporting-periods/{id}/reports` | List reports covering a period | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/reports/{id}` | Fetch a report | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/reports/{id}/revisions` | List amendments superseding this report | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/reports/{id}/file` | File a DRAFT report | Treasurer |
| POST | `/disclosure/reports/{id}/amend` | Amend a FILED report | Treasurer |
| POST | `/disclosure/reports/{id}/audit-open` | Open an audit (FILED → UNDER_AUDIT) | RegulatorAuditor |
| POST | `/disclosure/reports/{id}/audit-close` | Close an audit (UNDER_AUDIT → FILED) | RegulatorAuditor |
| POST | `/disclosure/reports/{id}/penalty/waive` | Waive an assessed penalty | RegulatorAuditor |
| POST | `/disclosure/registrants` | Register a lobbying registrant (starts ACTIVE) | LobbyRegistrant |
| GET | `/disclosure/registrants/{id}` | Fetch a registrant | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/registrants/{id}/terminate` | Terminate own registration | LobbyRegistrant |
| POST | `/disclosure/registrants/{id}/clients` | Add a client under a registrant | LobbyRegistrant |
| GET | `/disclosure/registrants/{id}/clients` | List a registrant's clients | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/clients/{id}` | Fetch a client | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/clients/{id}/deactivate` | Deactivate a client (ACTIVE → INACTIVE) | LobbyRegistrant |
| POST | `/disclosure/lobbying-periods` | Create a lobbying reporting period | RegulatorAuditor |
| GET | `/disclosure/lobbying-periods/{id}` | Fetch a lobbying reporting period | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/lobbying-periods/{id}/close` | Close a lobbying period; certify spend | RegulatorAuditor |
| POST | `/disclosure/registrants/{id}/activities` | Record a lobbying activity | LobbyRegistrant |
| GET | `/disclosure/registrants/{id}/activities` | List a registrant's activities | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/clients/{id}/activities` | List a client's activities | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/lobbying-periods/{id}/activities` | List activities under a lobbying period | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/activities/{id}` | Fetch a lobbying activity | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| GET | `/disclosure/activities` | Public-search lobbying activities | Treasurer, RegulatorAuditor, LobbyRegistrant, PublicViewer |
| POST | `/disclosure/activities/{id}/void` | Void a recorded activity | LobbyRegistrant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNER` | 403 |
| `ERR_COMMITTEE_NOT_FOUND` | 404 |
| `ERR_CONTRIBUTION_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_PERIOD_NOT_FOUND` | 404 |
| `ERR_REGISTRANT_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_ACTIVITY_NOT_FOUND` | 404 |
| `ERR_LOBBYING_PERIOD_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_COMMITTEE_NOT_PENDING` | 409 |
| `ERR_COMMITTEE_NOT_ACTIVE` | 409 |
| `ERR_CONTRIBUTION_NOT_RECORDED` | 409 |
| `ERR_CONTRIBUTION_NOT_DEPOSITED` | 409 |
| `ERR_CONTRIBUTION_NOT_VOIDABLE` | 409 |
| `ERR_CONTRIBUTION_REVIEW_INVALID` | 409 |
| `ERR_REPORT_NOT_DRAFT` | 409 |
| `ERR_REPORT_NOT_FILED` | 409 |
| `ERR_REPORT_NOT_UNDER_AUDIT` | 409 |
| `ERR_PENALTY_NOT_ASSESSED` | 409 |
| `ERR_PERIOD_NOT_OPEN` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_REGISTRANT_NOT_ACTIVE` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_ACTIVITY_NOT_VOIDABLE` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_ACTIVITY_OVERLAP` | 409 |
| `ERR_PROHIBITED_SOURCE` | 409 |
| `ERR_CONTRIBUTION_LIMIT_EXCEEDED` | 409 |
