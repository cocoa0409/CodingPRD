# Receivership Fiduciary API — Product Requirements Document

## 1. Introduction

When a court appoints a receiver over a distressed enterprise, the appointment order creates a fiduciary estate that must be administered under continuous judicial supervision. The receiver marshals and inventories the debtor's assets, decides which claims of creditors and investors will be allowed and in what amounts, retains professionals whose fees are charged against the estate, reports to the court on a fixed cadence, and ultimately proposes a plan for distributing the estate's cash under a strict priority waterfall — all before the court will discharge the receiver and close the case. Every one of those acts leaves a paper trail, and most of the consequential ones require the court's approval before they take effect.

This document specifies the Receivership Fiduciary API, the system of record for that administration. The API enforces a deliberate segregation of duties: the `Receiver` files, marshals, determines, and pays, while the `Court` alone adjudicates — ruling on engagements, fee applications, authorization requests, status reports, and distribution plans, ordering claim reconsideration, voiding payments, and granting discharge. A logical clock governs every business timestamp so that bar dates, reporting deadlines, and overdue flags are deterministic. All endpoints are mounted under the `/v1` prefix, and all estate arithmetic is carried in integer cents under a conservation invariant: every dollar that enters the estate through liquidation is accounted for, at all times, as cash on hand, paid professional fees, net paid distributions, or approved expenditures.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly to every resource and endpoint in the system.

### 2.1. User and Role-Based Access Control

Every request must carry the `X-User-Role` header, declaring the operational capacity in which the user acts; an `X-User-ID` header identifying the acting user is accepted but never inspected, and neither authentication nor authorization consults it. The system recognizes exactly four roles, spelled as follows: `Court`, `Receiver`, `Creditor`, and `SystemAdmin`. A request whose `X-User-Role` header is missing or does not name one of these four roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted on the targeted endpoint — for example, a `Receiver` attempting to adjudicate its own fee application, or a `Creditor` attempting to liquidate an asset — is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is always evaluated before authorization, and both are evaluated before any request-shape, existence, state, or fiscal check.

All four roles use opaque operator identities. When `X-User-Role` is `Court`, `X-User-ID` is an opaque operator identifier (for example, a chambers clerk) that is never the `id` of any persisted entity; the server does not compare it against any resource's foreign key. When `X-User-Role` is `Receiver`, `X-User-ID` is likewise an opaque operator identifier — the receiver named on a case is recorded as data in `appointed_receiver_name`, not as an access-control identity, and no resource's `id` is ever compared to the header. When `X-User-Role` is `Creditor`, `X-User-ID` is an opaque claimant account identifier that is never an entity `id`; no ownership scoping is enforced — a creditor may read the public estate record without restriction to their own claims. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque test-harness operator identifier, never an entity `id`, and the role controls only the logical clock.

The division of labor is asymmetric by design. The `Court` appoints the receiver by creating the case, adjudicates every instrument the receiver files, reconsiders claims, voids paid distributions, and discharges the estate. The `Receiver` marshals and liquidates assets, determines claims, proposes engagements, files fee applications and status reports, seeks authorization for out-of-ordinary-course actions, files and amends the distribution plan, and executes payments. The `Creditor` files claims — a filing the `Receiver` may also perform on a creditor's behalf — and otherwise reads. The `SystemAdmin` only advances the logical clock.

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

All error API responses (4xx and 5xx status codes) follow this standard envelope format:

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items actually returned is less than `total_count`.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties broken by `id` ascending. Two payment listings break from the default: the payments of a claim are returned ordered by priority-class rank ascending, and the payments of a plan are returned ordered by priority-class rank ascending with ties broken by the associated claim's `created_at` ascending and any remaining ties broken by the payment's `id`. The ranking itself — `SECURED` first, then `PRIORITY`, then `GENERAL`, then `INVESTOR` — is defined in §3.7.

### 2.4. The Estate Ledger: Cash Position, Marshalled Value, and Conservation

Each case carries three derived totals and a derived posture that together form the estate ledger. The `cash_on_hand_cents` of a case is the sum of `liquidation_value_cents` over its assets in `LIQUIDATED` status, minus the sum of `approved_amount_cents` over fee applications in `PAID` status, minus the sum of `paid_amount_cents` over distribution payments in `PAID` status, minus the sum of `amount_cents` over approved authorization requests of type `EXPENDITURE`. The `marshalled_value_cents` is the sum, over every asset of the case that is not `ABANDONED`, of the asset's `liquidation_value_cents` when the asset is `LIQUIDATED` and of its `estimated_value_cents` otherwise. The `allowed_claims_total_cents` is the sum of `allowed_amount_cents` over the case's claims currently in `ALLOWED` status. The `posture` of a case is `CASH_CONSTRAINED` whenever `cash_on_hand_cents` is strictly less than the case's `operating_reserve_cents`, and `NORMAL` otherwise; the flag flips automatically as cash moves.

A conservation invariant holds at all times: the case's `cash_on_hand_cents`, plus the approved amounts of all paid fee applications, plus the paid amounts of distribution payments still in `PAID` status (a payment later voided no longer counts, because voiding credits the cash back), plus the amounts of all approved `EXPENDITURE` authorizations, exactly equals the total liquidation proceeds. Scheduled distribution payments never debit cash, so they do not appear in the ledger until actually paid. All derived values are recomputed immediately as part of the mutating request — consistency is immediate, and every mutation is visible in that request's own response.

### 2.5. The Logical Clock and the Court's Reporting Calendar

The server maintains a logical clock that is the sole source of every business timestamp. Before the clock has ever been set, its value is exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time. A test-driving capability restricted to `SystemAdmin` sets the clock to a supplied `to_iso8601` instant and returns the new `current_utc`; the clock is set unconditionally, even to an instant earlier than its current value. All business timestamps — a claim's `filed_at`, an asset's `liquidated_at`, an authorization request's `decided_at`, a claim determination's `determined_at`, a plan's `approved_at`, a payment's `paid_at` — are read from this clock, as are all overdue evaluations. Computed flags such as `report_overdue` reflect the new time on the next read after the clock advances.

The reporting calendar of a case is anchored at `appointment_effective_at`. The case's `next_report_period_start` is the latest `period_end` among the case's non-`REJECTED` `PERIODIC` status reports; if no such report exists, it is `appointment_effective_at`. The case's `report_overdue` flag is true exactly when the current logical time is strictly greater than `next_report_period_start` plus `reporting_interval_days` days — at the precise instant the interval elapses the report is not yet overdue. Calendar arithmetic uses datetimes at second precision with half-open interval semantics.

### 2.6. Monetary Representation and Rounding

Every monetary quantity in the system — values, fees, claims, reserves, payments — is an integer number of cents. No floating-point money appears anywhere. Rounding occurs in exactly two places. Fee requests on an hourly engagement round each individual time-entry line to whole cents using round-half-up before the lines are summed; the rounding of each entry precedes summation, and only then are expenses added (summing first and rounding once can differ by a cent, and that order is not the contract). Fee requests on a contingent engagement round the percentage-of-recovery product to whole cents, round-half-up, before expenses are added. The distribution waterfall allocates pro-rata shares by truncating each raw share down to a whole cent and then sweeping the leftover cents deterministically, as specified in §3.7. Claim bucketing, the estate ledger, and fee-cap arithmetic involve no rounding at all — they are exact integer computations.

### 2.7. Optimistic Concurrency Control on Estate Cash

Two write endpoints debit estate cash against a balance the client observed earlier, and both are guarded by optimistic concurrency control on the case: paying an approved fee application (`POST /v1/fee-applications/{id}/pay`) and paying a scheduled distribution payment (`POST /v1/distribution-payments/{id}/pay`). Each of these requests must carry `expected_case_version`, a non-optional input holding the `version` of the case as the client last read it. If the case's current `version` has advanced past that value — because a liquidation, a fee payment, an expenditure approval, a distribution payment, or a void has since landed — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). The rule is purely a stale-version check: it does not depend on two requests overlapping in time. No other endpoint accepts a version field; optimistic concurrency applies to these two cash-debiting payment endpoints and nowhere else.

### 2.8. Resource Identity and Common Fields

Every resource in the system — cases, assets, claims, engagements, fee applications, authorization requests, status reports, distribution plans, and distribution payments — carries the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` are ISO 8601 UTC timestamps at second precision (for example, `2026-08-01T00:00:00Z`), recording creation and the most recent modification. The `version` is an integer that increments on every mutation of the resource, including mutations that only recompute derived fields; a newly created case starts at `version` 1. When an operation on one resource recomputes a derived field of another — a liquidation refreshing the case's cash, for example — the recomputation is a mutation of that other resource, refreshing its `updated_at` and, where the scaffold of the operation says so, incrementing its `version`.

### 2.9. Flat Resource Addressing and Referential Scope

All nine resources are addressed as top-level collections under `/v1`; relationships are expressed by foreign keys in request bodies and by filters in list endpoints, never by deep nesting. The case-scoped collection listings — the assets, engagements, authorization requests, and status reports of a case — validate path identifiers left to right, so a request naming a nonexistent case fails on the case `id` before any other consideration. Existence checking then extends to foreign keys carried in request bodies, which must not only exist but belong to the implied scope: a secured claim's `collateral_asset_id` must name an asset of the same case, an authorization request's `related_asset_id` must likewise resolve within its case, and a fee application's `engagement_id` must name an existing engagement. A path identifier or referenced foreign key that does not exist, or that exists outside the implied scope, is rejected with `ERR_NOT_FOUND` (HTTP 404). A request to a path the API does not define — including a defined path under an unsupported method — is likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.10. The Validation Cascade and Error Priority

A request is validated against an ordered cascade; when several rules would fail, the earliest category determines the error surfaced. The order is:

1. Authentication: the `X-User-Role` header is present and names a recognized role, else `ERR_UNAUTHENTICATED`.
2. Authorization: the acting role is permitted on the endpoint, else `ERR_FORBIDDEN`.
3. Request shape: required fields are present, types are valid, enum values are in range, and conditional requirements are satisfied — `collateral_asset_id` exactly when the claim is `SECURED`, `hourly_rate_cents` exactly when the engagement is `HOURLY`, `contingency_pct` exactly when it is `CONTINGENT`, a non-empty `time_entries` array exactly when the application is hourly, `recovery_basis_cents` exactly when it is contingent, `related_asset_id` exactly when the request type is `ASSET_LIQUIDATION` or `ASSET_ABANDONMENT`, `allowed_amount_cents` required when the determination is `ALLOWED` (it is accepted but ignored when the determination is `DISALLOWED`), `approved_amount_cents` required when a fee-application decision is an approval (it is accepted but ignored on a rejection), amounts strictly positive where required, and `period_start` before `period_end`. Any failure here is `ERR_INVALID_REQUEST` (HTTP 400).
4. Existence and scope of path identifiers and body foreign keys, else `ERR_NOT_FOUND`.
5. The optimistic-concurrency check on the two cash-debiting payment endpoints, else `ERR_STALE_CASE_VERSION`.
6. From-state validity of the requested transition — liquidation requires an `IDENTIFIED` asset, a decision requires the instrument's pending state, a fee payment requires an `APPROVED` application, a distribution payment requires a `SCHEDULED` payment, discharge requires a `DISTRIBUTING` case — else `ERR_INVALID_STATE` (HTTP 409).
7. Cross-entity state gates: the owning case must be in the required status for the operation (`ERR_CASE_NOT_ACTIVE`), the engagement must be `APPROVED` when a fee application is filed (`ERR_ENGAGEMENT_NOT_APPROVED`), the plan must still be `APPROVED` when a payment is voided (`ERR_PLAN_NOT_EXECUTING`), and the case must be `DISTRIBUTING` when a `FINAL` report is filed.
8. The court-approval gate on liquidating or abandoning an asset whose estimated value exceeds the case's authority limit — `ERR_AUTHORIZATION_REQUIRED` when no authorization is supplied and `ERR_AUTHORIZATION_MISMATCH` when a supplied one is wrong in state, type, or asset.
9. The court-calendar gates: a claim filed strictly after the bar date (`ERR_CLAIM_BARRED`, HTTP 422) and a plan filing or amendment attempted while a periodic report is overdue (`ERR_STATUS_REPORT_OVERDUE`, HTTP 422).
10. Uniqueness, interval, and aggregate constraints, evaluated within this category in a fixed sub-order: (a) duplicate `case_number` within the same `court_jurisdiction` (`ERR_DUPLICATE_CASE_NUMBER`); (b) a second `PROPOSED` or `APPROVED` engagement with the same `role_type` on the same case (`ERR_ENGAGEMENT_ALREADY_ACTIVE`); (c) a second plan in `FILED` or `APPROVED` status on the case (`ERR_PLAN_ALREADY_OPEN`); (d) plan filing while any claim of the case remains `FILED` (`ERR_UNDETERMINED_CLAIMS`); (e) overlapping fee-application periods on one engagement (`ERR_FEE_PERIOD_OVERLAP`); (f) report-period overlap (`ERR_REPORT_PERIOD_OVERLAP`) evaluated strictly before report-period contiguity (`ERR_REPORT_PERIOD_GAP`); (g) the senior-class payment gate (`ERR_SENIOR_CLASS_UNPAID`); and (h) the aggregate discharge preconditions (`ERR_DISCHARGE_BLOCKED`).
11. Referenced-entity usability: the collateral asset named by a secured claim must not be `ABANDONED`, else `ERR_COLLATERAL_NOT_ELIGIBLE`.
12. Fiscal checks, always last: cash sufficiency for fee payment, distribution payment, and expenditure approval (`ERR_INSUFFICIENT_ESTATE_FUNDS`); the reserve not exceeding cash at plan filing (`ERR_RESERVE_EXCEEDS_POOL`, HTTP 422); the engagement fee cap at approval (`ERR_FEE_CAP_EXCEEDED`, HTTP 422); approved not exceeding requested (`ERR_AMOUNT_EXCEEDS_REQUEST`, HTTP 422); and allowed not exceeding filed (`ERR_ALLOWED_EXCEEDS_FILED`, HTTP 422).

Beyond the conditional prohibitions of rule 3, a field that an endpoint's contract does not use is accepted and ignored rather than rejected.

## 3. Business Logic & Workflows

### 3.1. Opening the Estate: Appointment and Case Creation

A receivership begins when the `Court` creates the case, supplying the `case_number`, the `court_jurisdiction` (for example, "S.D.N.Y."), the `debtor_name`, and the `appointed_receiver_name`. The appointment order's scope is captured on the case itself: `appointment_effective_at` is the effective timestamp of the appointment and anchors the reporting calendar; `authority_limit_cents` is the ceiling below which the receiver may dispose of assets without asking the court first; `business_operation_authorized` records whether the order authorizes continued operation of the debtor's business; `bar_date` is the claims bar date; `reporting_interval_days` fixes the cadence of periodic reporting; and `operating_reserve_cents` sets the cash floor used by the posture derivation. Of these inputs, `reporting_interval_days` must be strictly positive, while `authority_limit_cents` and `operating_reserve_cents` may be zero but never negative.

The `case_number` must be unique within its `court_jurisdiction`; a second case filed with the same number in the same jurisdiction is rejected with `ERR_DUPLICATE_CASE_NUMBER`. A newly created case starts in `ACTIVE` status with `cash_on_hand_cents`, `marshalled_value_cents`, and `allowed_claims_total_cents` all zero, `posture` equal to `NORMAL`, and `version` 1. Because no reports exist yet, `next_report_period_start` is the appointment timestamp, and `report_overdue` becomes true only once the logical clock passes that anchor plus one full reporting interval. The case remains `ACTIVE` until approval of a distribution plan moves it to `DISTRIBUTING`, and it leaves `DISTRIBUTING` only by discharge, its terminal state `DISCHARGED`.

### 3.2. Marshalling the Estate: Asset Inventory, Liquidation, and Abandonment

The `Receiver` builds the estate inventory by marshalling assets, each created against a payload carrying the owning `case_id`, a free-text `description`, an `asset_class` drawn from `REAL_PROPERTY`, `CASH`, `SECURITIES`, `RECEIVABLE`, `EQUIPMENT`, or `OTHER`, and an `estimated_value_cents` that may be zero but never negative. A marshalled asset starts `IDENTIFIED`, and its arrival immediately recomputes the case's `marshalled_value_cents`. Marshalling requires only that the named case exist; the case's own status is not consulted.

Liquidation converts an `IDENTIFIED` asset to `LIQUIDATED`. The receiver supplies the realized `liquidation_value_cents`, which may be zero but never negative, and the transition stamps `liquidated_at` from the logical clock, adds the realized proceeds to the case's `cash_on_hand_cents`, recomputes `marshalled_value_cents` and `posture`, and increments the case's `version`. Two guards stand in front of the transition: the asset must actually be `IDENTIFIED` (otherwise `ERR_INVALID_STATE`), and the owning case must be `ACTIVE` (otherwise `ERR_CASE_NOT_ACTIVE`).

Above the authority limit, liquidation additionally requires the court's prior approval. When the asset's `estimated_value_cents` is strictly greater than the case's `authority_limit_cents`, the request must carry an `authorization_id` referencing an `APPROVED` authorization request of the same case whose `request_type` is `ASSET_LIQUIDATION` and whose `related_asset_id` names this very asset; a missing `authorization_id` is rejected with `ERR_AUTHORIZATION_REQUIRED`, while one that resolves to a request that is not approved, has the wrong type, or points at a different asset is rejected with `ERR_AUTHORIZATION_MISMATCH`. When the estimated value is less than or equal to the limit — equality included — no authorization is required at all.

Abandonment follows the identical pattern for an asset the estate is better off without: the same `IDENTIFIED` from-state, the same `ACTIVE` case gate, and the same authority-limit test, except that the linked authorization request must have `request_type` `ASSET_ABANDONMENT`. An abandoned asset moves to `ABANDONED`, and the case's `marshalled_value_cents` is recomputed with the asset now excluded. Abandonment does not touch secured claims that named the asset as collateral; instead, the consequence is deferred to determination time, where an `ABANDONED` collateral asset contributes a collateral value of zero to the bucketing described in §3.4. Both terminal asset states — `LIQUIDATED` and `ABANDONED` — are irreversible.

### 3.3. Seeking the Court: Authorization Requests and Estate Expenditures

Whenever the receiver needs court approval for an out-of-ordinary-course act, it files an authorization request against the case, supplying the `case_id`, a `request_type` of `EXPENDITURE`, `ASSET_LIQUIDATION`, `ASSET_ABANDONMENT`, or `BUSINESS_DECISION`, a narrative `description`, and the `amount_cents` at issue, which must be strictly positive. The `related_asset_id` is required exactly when the request concerns an asset — the liquidation and abandonment types — and is forbidden on the other two types. Filing requires the owning case to be `ACTIVE`, failing with `ERR_CASE_NOT_ACTIVE` otherwise, and the request starts life `SUBMITTED`.

Only the `Court` rules on the request. Approval stamps `decided_at` from the logical clock and moves the request to `APPROVED`; rejection also stamps `decided_at` and moves it to `DENIED`; both are terminal, and ruling on an already-decided request is rejected with `ERR_INVALID_STATE`. An approved liquidation or abandonment request is what satisfies the authority-limit gate of §3.2 when the receiver later cites it as the `authorization_id`.

Approval of an `EXPENDITURE` request is itself a cash event. The court may approve only while the case's `cash_on_hand_cents` is at least the requested `amount_cents`, failing with `ERR_INSUFFICIENT_ESTATE_FUNDS` otherwise. On approval the amount is debited from `cash_on_hand_cents` immediately, the case's `version` is incremented, and `posture` is recomputed. The other three request types carry no cash effect on approval.

### 3.4. Claims: Filing, the Bar Date, Determination, and Reconsideration

Claims enter the estate from two directions: a `Creditor` files its own claim, or the `Receiver` files on a creditor's behalf. The filing names the owning `case_id`, the `creditor_name`, a `creditor_type` of `SECURED`, `PRIORITY_TAX`, `PRIORITY_WAGE`, `GENERAL_UNSECURED`, or `INVESTOR`, and a strictly positive `filed_amount_cents`. The case must be `ACTIVE` at filing, failing with `ERR_CASE_NOT_ACTIVE` otherwise. The system stamps `filed_at` from the logical clock, and the bar-date gate is evaluated against it: a claim whose `filed_at` falls strictly after the case's `bar_date` is rejected with `ERR_CLAIM_BARRED` (HTTP 422), while a filing landing exactly on the bar date is timely.

A secured claim must name its collateral. The `collateral_asset_id` is required exactly when `creditor_type` is `SECURED` — omitting it there, or supplying it for any other creditor type, is `ERR_INVALID_REQUEST`. The referenced asset must exist within the same case (otherwise `ERR_NOT_FOUND`) and must not be `ABANDONED` (otherwise `ERR_COLLATERAL_NOT_ELIGIBLE`). A filed claim starts in `FILED` status with `allowed_amount_cents`, all four class buckets, and `determined_at` all null.

Determination is the receiver's adjudication of the claim and comes in two forms, selected by the `determination` field of the determination call, which names the outcome as `ALLOWED` or `DISALLOWED`. Determining a claim as `ALLOWED` requires the owning case to be `ACTIVE` or `DISTRIBUTING` (else `ERR_CASE_NOT_ACTIVE`) and requires `allowed_amount_cents` to be present (else `ERR_INVALID_REQUEST`), to be zero or greater, and to be no greater than `filed_amount_cents` (else `ERR_ALLOWED_EXCEEDS_FILED`, HTTP 422). The determination then splits the allowed amount into class buckets according to the creditor type. For a `SECURED` claim, the collateral basis is zero when the collateral asset is `ABANDONED`, the asset's `liquidation_value_cents` when it is `LIQUIDATED` at determination time, or its `estimated_value_cents` when it is still `IDENTIFIED`; the `secured_allowed_cents` bucket is the smaller of the allowed amount and that basis, and whatever remains of the allowed amount spills into `general_allowed_cents` as a deficiency claim, with `priority_allowed_cents` and `investor_allowed_cents` set to zero. For a `PRIORITY_WAGE` claim, `priority_allowed_cents` is the smaller of the allowed amount and the statutory wage-priority cap of $15,150.00 — that is, 1,515,000 cents — and any excess over the cap lands in `general_allowed_cents`, with the secured and investor buckets zero. A `PRIORITY_TAX` claim places its entire allowed amount in `priority_allowed_cents`; a `GENERAL_UNSECURED` claim places it all in `general_allowed_cents`; and an `INVESTOR` claim places it all in `investor_allowed_cents`, subordinated behind every creditor class. In every case the four buckets sum exactly to `allowed_amount_cents`. Determination stamps `determined_at` from the logical clock and recomputes the case's `allowed_claims_total_cents`; if that total changed while a distribution plan of the case is sitting `FILED`, the plan's premise is stale and the plan is automatically moved to `WITHDRAWN`. Determining a claim as `DISALLOWED` — the alternate outcome of the same determination act — requires only the case gate, leaves `allowed_amount_cents` and all four buckets null, and stamps `determined_at`.

Reconsideration belongs to the court. A `Court`-ordered reconsideration returns an `ALLOWED` or `DISALLOWED` claim to `FILED`, provided the case is `ACTIVE` or `DISTRIBUTING`. Reconsidering an allowed claim clears `allowed_amount_cents` and all four class buckets to null, resets `determined_at` to null, recomputes `allowed_claims_total_cents` downward by the cleared amount, withdraws any `FILED` plan of the case, and cancels every distribution payment of that claim still in `SCHEDULED` status — moving each to `CANCELLED` with no cash movement, since scheduled payments never debited the estate. Reconsidering a disallowed claim simply resets `determined_at` to null. Because the claim cycle has no terminal state of its own, a reconsidered claim may be determined anew, with its buckets re-derived from whatever the collateral and cap values are at that later moment; the cycle freezes only when the enclosing case is discharged.

### 3.5. Retaining Professionals: Engagements, Fee Applications, and the Fee Cap

The receiver administers the estate through retained professionals. Proposing an engagement names the `case_id`, the lead `professional_name`, the `firm_name`, a `role_type` of `COUNSEL`, `ACCOUNTANT`, `AUCTIONEER`, or `BROKER`, a `fee_arrangement` of `HOURLY` or `CONTINGENT`, and a strictly positive `fee_cap_cents` — the court-approved not-to-exceed budget for the engagement. An `HOURLY` engagement must supply its default `hourly_rate_cents` and must not supply `contingency_pct`; a `CONTINGENT` engagement must supply `contingency_pct` — the fraction of the recovery charged, such as 0.10 — and must not supply `hourly_rate_cents`. Beyond those presence rules, `hourly_rate_cents` may be any integer and `contingency_pct` any number; neither is range-checked. One professional per discipline is the rule: a second engagement on the same case with the same `role_type` while one is `PROPOSED` or `APPROVED` is rejected with `ERR_ENGAGEMENT_ALREADY_ACTIVE`. A proposed engagement starts `PROPOSED` and does no work until the court rules. Proposing an engagement requires only that the named case exist; the case's status is not consulted at proposal time.

The `Court` decides each proposed engagement. Approval requires the case to be `ACTIVE` or `DISTRIBUTING` (else `ERR_CASE_NOT_ACTIVE`) and moves the engagement to `APPROVED`; rejection carries no further precondition and moves it to `DENIED`, a terminal state.

Against an `APPROVED` engagement — and only an `APPROVED` one, with filings against a `PROPOSED`, `DENIED`, `EXHAUSTED`, or `CLOSED` engagement rejected with `ERR_ENGAGEMENT_NOT_APPROVED` — the receiver files fee applications. Each application names its `engagement_id` and covers a half-open period from `period_start` (inclusive) to `period_end` (exclusive), with `period_start` strictly before `period_end`; the periods of non-`DENIED` applications on the same engagement must not overlap, failing with `ERR_FEE_PERIOD_OVERLAP`, though gaps and abutting periods are permitted. The requested amount is computed by the server at filing, not supplied. On an hourly engagement the application carries a non-empty `time_entries` array, each entry pairing a numeric `hours` quantity with an integer `rate_cents` (an entry failing either is `ERR_INVALID_REQUEST`); the value of each entry is its hours multiplied by its rate, rounded half-up to whole cents first, and the `requested_amount_cents` is the sum of those rounded lines plus the `expenses_cents` sought, which may be zero. Because these conditional shape rules hinge on the engagement's arrangement, the engagement's existence is verified before them: filing against a nonexistent `engagement_id` fails with `ERR_NOT_FOUND` even when `time_entries` or `recovery_basis_cents` would also fail. On a contingent engagement `time_entries` must be absent or empty, the application instead carries the `recovery_basis_cents` the percentage applies to, and `requested_amount_cents` is the product of the engagement's `contingency_pct` and `recovery_basis_cents`, rounded half-up to whole cents, plus `expenses_cents`. A filed application starts `FILED` with `approved_amount_cents` null.

The court rules on each filed application. An approval must supply `approved_amount_cents` (else `ERR_INVALID_REQUEST`) not exceeding the computed `requested_amount_cents` (else `ERR_AMOUNT_EXCEEDS_REQUEST`, HTTP 422). The fee cap is then enforced against commitments: the sum of `approved_amount_cents` over the engagement's applications already in `APPROVED` or `PAID` status, plus the newly approved amount, must not exceed `fee_cap_cents` — reaching the cap exactly is permitted — and a breach is rejected with `ERR_FEE_CAP_EXCEEDED` (HTTP 422). Rejection moves the application to `DENIED`, terminal. The court's decision payload carries a `decision` of `APPROVE` or `REJECT`, the same shape used for engagements, authorization requests, status reports, and plans.

Payment of an approved application is the receiver's act and is one of the two OCC-guarded cash writes: the request must carry `expected_case_version` equal to the case's current `version`, failing with `ERR_STALE_CASE_VERSION` (HTTP 412) on mismatch. The case must be `ACTIVE` or `DISTRIBUTING` (else `ERR_CASE_NOT_ACTIVE`), and its `cash_on_hand_cents` must cover the `approved_amount_cents` (else `ERR_INSUFFICIENT_ESTATE_FUNDS`). Paying moves the application to `PAID`, debits the approved amount from `cash_on_hand_cents`, increments the case's `version`, recomputes `posture`, and recomputes the engagement's `total_fees_paid_cents` — the running sum of approved amounts over its `PAID` applications. When that running total reaches or exceeds `fee_cap_cents`, the engagement automatically moves from `APPROVED` to `EXHAUSTED`, and an exhausted engagement rejects any further fee applications with `ERR_ENGAGEMENT_NOT_APPROVED`. When the case is ultimately discharged, every engagement still `APPROVED` or `EXHAUSTED` is closed for the receiver, ending in the terminal `CLOSED` state.

### 3.6. Reporting to the Court: Periodic and Final Status Reports

The receiver accounts to the court through status reports, each filed with the owning `case_id`, a `report_type` of `PERIODIC` or `FINAL`, the covered `period_start` and `period_end`, and a free-text `narrative`. Two case gates apply at filing: a `PERIODIC` report requires the case to be `ACTIVE`, while a `FINAL` report may be created only while the case is `DISTRIBUTING`; the wrong case status yields `ERR_CASE_NOT_ACTIVE`. The covered period is half-open — `period_start` inclusive, `period_end` exclusive — with `period_end` strictly after `period_start` (else `ERR_INVALID_REQUEST`).

Contiguity and non-overlap keep the calendar gapless. The half-open period must not intersect the period of any other non-`REJECTED` report of the same case, failing with `ERR_REPORT_PERIOD_OVERLAP`, and the report's `period_start` must equal the case's current `next_report_period_start` exactly, failing with `ERR_REPORT_PERIOD_GAP`. The overlap check is always evaluated before the gap check, so a report that collides with an existing one surfaces the overlap error even if its start is also wrong. A filed report starts in `FILED` status.

The court then rules. Acceptance moves the report to `ACCEPTED` and advances the reporting calendar: `next_report_period_start` and `report_overdue` are recomputed, the former becoming the latest `period_end` among non-`REJECTED` `PERIODIC` reports. Rejection moves the report to `REJECTED`; a rejected report neither advances the calendar nor participates in overlap or contiguity checks, so the receiver responds by filing a corrected new report covering the same ground. Both outcomes are terminal for the report. While the case's `report_overdue` flag is true, the court-calendar gate of §3.7 blocks any distribution-plan filing or amendment with `ERR_STATUS_REPORT_OVERDUE` — missed reporting halts distributions.

### 3.7. The Distribution Plan: Filing, Approval, and the Priority Waterfall

When the claims picture is settled, the receiver files a distribution plan naming the `case_id` and a `reserve_cents` the court will withhold from the distribution pool. Filing re-runs a battery of gates: the case must be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`); the case's `report_overdue` flag must be false (else `ERR_STATUS_REPORT_OVERDUE`, HTTP 422); no claim of the case may remain `FILED` (else `ERR_UNDETERMINED_CLAIMS`); no other plan of the case may be `FILED` or `APPROVED` (else `ERR_PLAN_ALREADY_OPEN`); and `reserve_cents` must be non-negative and no greater than the current `cash_on_hand_cents` (else `ERR_RESERVE_EXCEEDS_POOL`, HTTP 422). At filing the plan pins `pool_snapshot_cents` — the provisional pool, computed as the filing-time `cash_on_hand_cents` minus `reserve_cents` — which serves as the advisory figure circulated on court notice. The plan starts `FILED`, with `approved_at` null.

The court's approval is the system's largest cascade. Approving recomputes the waterfall in its final variant at approval time: the pool is the case's `cash_on_hand_cents` at that moment minus `reserve_cents`, which may differ from the pinned `pool_snapshot_cents` if fee payments or expenditure approvals moved cash between filing and approval; if that difference is negative the pool is treated as zero and the approval generates no payment rows. Approval stamps `approved_at`, moves the plan to `APPROVED`, moves the case from `ACTIVE` to `DISTRIBUTING`, and — on the case's entry into `DISTRIBUTING` — materializes the payment schedule: one distribution payment row per claim-and-class-bucket pair whose computed amount is greater than zero, each carrying its `plan_id`, `claim_id`, `priority_class`, and a `scheduled_amount_cents`, starting in `SCHEDULED` status. Rejection moves the plan to `REJECTED` with no further effect.

The waterfall itself pays classes in strict rank order — `SECURED` (rank 1), then `PRIORITY` (rank 2), then `GENERAL` (rank 3), then `INVESTOR` (rank 4) — over the claims of the case currently in `ALLOWED` status, drawing each class's total from the corresponding bucket: `secured_allowed_cents`, `priority_allowed_cents`, `general_allowed_cents`, and `investor_allowed_cents`. For each class in turn, the class total is the sum of that class's bucket over the allowed claims; a class whose total is zero is skipped entirely, generating no rows and consuming no pool. If the remaining pool covers the class total, every bucket in the class is paid in full and the pool is reduced by the class total. Otherwise the class is paid pro rata: each bucket's raw share is the remaining pool multiplied by the bucket and divided by the class total, truncated down to a whole cent; the cents left over by truncation — always fewer than the number of buckets in the class, so a single pass suffices — are distributed one cent at a time to buckets ordered by bucket amount descending, ties broken by the owning claim's `created_at` ascending, never by identifier. The pool is then exhausted, classes after it generate no rows, and any bucket whose computed amount is zero gets no payment row at all.

Two system transitions manage the plan after filing. If the case's `allowed_claims_total_cents` changes while the plan is `FILED` — because a claim was determined or reconsidered — the plan's premise is stale and it moves automatically to `WITHDRAWN`, a terminal state. And once every payment of an approved plan has left `SCHEDULED` — each `PAID`, `VOIDED`, or `CANCELLED` — the plan moves automatically from `APPROVED` to `EXECUTED`, also terminal.

A rejected plan is not the end. The receiver may amend a `REJECTED` plan back to `FILED`, optionally supplying a new `reserve_cents`; amendment re-runs every filing validation — case `ACTIVE`, no overdue report, no undetermined claims, no other open plan, and the reserve (the new value when provided, the existing one otherwise) within current cash — and re-pins `pool_snapshot_cents` from the cash position at amendment time. Amending a plan that is not `REJECTED` is rejected with `ERR_INVALID_STATE`. The plan named in the path is resolved before the optional new reserve is validated, so a request naming a nonexistent plan fails with `ERR_NOT_FOUND` even when the supplied `reserve_cents` is itself invalid.

### 3.8. Paying Creditors, Voiding Payments, and Discharging the Receiver

Payment rows exist only because a plan approval generated them; there is no way to create one directly. The receiver pays a `SCHEDULED` payment — the second of the two OCC-guarded cash writes — carrying `expected_case_version` equal to the case's current `version`, failing with `ERR_STALE_CASE_VERSION` (HTTP 412) on mismatch. Seniority is enforced across the plan: no payment of the same plan in a strictly senior class may still be `SCHEDULED` — `SECURED` before `PRIORITY` before `GENERAL` before `INVESTOR` — and a violation is rejected with `ERR_SENIOR_CLASS_UNPAID`; payments within the same class may be paid in any order. The case's `cash_on_hand_cents` must cover the `scheduled_amount_cents`, failing with `ERR_INSUFFICIENT_ESTATE_FUNDS` otherwise, and attempting to pay a payment that is not `SCHEDULED` fails with `ERR_INVALID_STATE`. A successful payment sets `paid_amount_cents` equal to `scheduled_amount_cents`, stamps `paid_at` from the logical clock, debits the scheduled amount from `cash_on_hand_cents`, increments the case's `version`, recomputes `posture`, and — when the payment was the last `SCHEDULED` row on its plan — bubbles the plan up to `EXECUTED`.

The court may void a payment that has been `PAID` — an uncashed check, for instance — but only while the payment's plan is still `APPROVED`; once the plan has reached `EXECUTED` the void window has closed and the attempt is rejected with `ERR_PLAN_NOT_EXECUTING`. Voiding moves the payment to `VOIDED` and credits `paid_amount_cents` back to the case's `cash_on_hand_cents`, incrementing the case's `version` and recomputing `posture`; the voided row retains its `paid_amount_cents` for audit even though the cash has returned. Separately, when the court reconsiders an allowed claim, every `SCHEDULED` payment generated for that claim moves automatically to `CANCELLED` with no cash movement — scheduled amounts never left the estate — and if that cancellation clears the plan's last `SCHEDULED` row, the plan becomes `EXECUTED`. Creditors and the public record read payments through two listings: the payments of a claim, ordered by class rank ascending, and the payments of a plan, ordered by class rank ascending and then by the claim's `created_at` ascending, each filterable by `status`, and the plan listing also by `priority_class`.

Discharge is the court's final act and is available only from `DISTRIBUTING` — a discharge attempted from `ACTIVE` is rejected with `ERR_INVALID_STATE`. Six aggregate preconditions must all hold, any failure surfacing as `ERR_DISCHARGE_BLOCKED`: some plan of the case has reached `EXECUTED`; no claim of the case remains `FILED`; no fee application of any engagement of the case remains `FILED` or `APPROVED`; a `FINAL` status report of the case has been `ACCEPTED`; no asset of the case remains `IDENTIFIED`; and `cash_on_hand_cents` is exactly zero. On discharge the case enters its terminal `DISCHARGED` status and every engagement still `APPROVED` or `EXHAUSTED` moves to `CLOSED`. With the case discharged, the claim-reconsideration cycle and every other case-gated operation freeze, because none of them accept a `DISCHARGED` case.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The table below is a navigational summary only — request payloads, derived-field behavior, side effects, and the conditions under which each call fails are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/cases` | Court appoints a receiver: create the receivership case (starts `ACTIVE`) | Court |
| GET | `/v1/cases/{id}` | Read a case including computed fields | Court, Receiver, Creditor |
| POST | `/v1/cases/{id}/discharge` | Court discharges the receiver after final accounting | Court |
| GET | `/v1/cases/{id}/assets` | List assets of a case (filterable by `status`, `asset_class`) | Court, Receiver |
| GET | `/v1/cases/{id}/engagements` | List professional engagements of a case (filterable by `status`, `role_type`) | Court, Receiver |
| GET | `/v1/cases/{id}/authorization-requests` | List authorization requests of a case (filterable by `status`, `request_type`) | Court, Receiver |
| GET | `/v1/cases/{id}/status-reports` | List status reports of a case (filterable by `report_type`, `status`) | Court, Receiver |
| POST | `/v1/assets` | Receiver marshals an asset into the estate inventory (starts `IDENTIFIED`) | Receiver |
| GET | `/v1/assets/{id}` | Read an asset | Court, Receiver |
| POST | `/v1/assets/{id}/liquidate` | Receiver liquidates an `IDENTIFIED` asset; authority-limit gate applies | Receiver |
| POST | `/v1/assets/{id}/abandon` | Receiver abandons a valueless `IDENTIFIED` asset; authority-limit gate applies | Receiver |
| GET | `/v1/assets/{id}/authorization-requests` | List authorization requests referencing an asset (filterable by `status`) | Court, Receiver |
| POST | `/v1/claims` | File a creditor/investor claim; bar-date gate applies | Receiver, Creditor |
| GET | `/v1/claims` | List claims with filters (`case_id`, `collateral_asset_id`, `status`, `creditor_type`) | Court, Receiver, Creditor |
| GET | `/v1/claims/{id}` | Read a claim including computed class buckets | Court, Receiver, Creditor |
| POST | `/v1/claims/{id}/determine` | Receiver determines a `FILED` claim (`ALLOWED` with `allowed_amount_cents`, or `DISALLOWED`) | Receiver |
| POST | `/v1/claims/{id}/reconsider` | Court orders reconsideration: claim returns to `FILED`, buckets cleared | Court |
| GET | `/v1/claims/{id}/payments` | List distribution payments of a claim, ordered by `priority_class` rank ascending | Court, Receiver, Creditor |
| POST | `/v1/engagements` | Receiver proposes retention of a professional (starts `PROPOSED`) | Receiver |
| GET | `/v1/engagements/{id}` | Read an engagement including `total_fees_paid_cents` | Court, Receiver |
| POST | `/v1/engagements/{id}/decide` | Court approves or denies a `PROPOSED` engagement | Court |
| GET | `/v1/engagements/{id}/fee-applications` | List fee applications of an engagement (filterable by `status`) | Court, Receiver |
| POST | `/v1/fee-applications` | Receiver files a fee application (starts `FILED`); requested amount computed | Receiver |
| POST | `/v1/fee-applications/{id}/decide` | Court approves (with `approved_amount_cents` not exceeding requested) or denies a `FILED` fee application | Court |
| POST | `/v1/fee-applications/{id}/pay` | Receiver pays an `APPROVED` fee application; OCC on the case version; debits estate cash | Receiver |
| POST | `/v1/authorization-requests` | Receiver seeks court approval for an out-of-ordinary-course action | Receiver |
| POST | `/v1/authorization-requests/{id}/decide` | Court approves or denies a `SUBMITTED` request; approving an `EXPENDITURE` debits estate cash immediately | Court |
| POST | `/v1/status-reports` | Receiver files a periodic or final status report (starts `FILED`) | Receiver |
| POST | `/v1/status-reports/{id}/decide` | Court accepts or rejects a `FILED` status report | Court |
| POST | `/v1/distribution-plans` | Receiver files a distribution plan (starts `FILED`); pool snapshot pinned | Receiver |
| GET | `/v1/distribution-plans` | List distribution plans with filters (`case_id`, `status`) | Court, Receiver, Creditor |
| GET | `/v1/distribution-plans/{id}` | Read a distribution plan including `pool_snapshot_cents` | Court, Receiver, Creditor |
| POST | `/v1/distribution-plans/{id}/decide` | Court approves (final waterfall, case to `DISTRIBUTING`, payment rows generated) or rejects a `FILED` plan | Court |
| POST | `/v1/distribution-plans/{id}/amend` | Receiver amends a `REJECTED` plan back to `FILED`, optionally with a new reserve | Receiver |
| GET | `/v1/distribution-plans/{id}/payments` | List payments of a plan, ordered by `priority_class` rank then claim `created_at` (filterable by `status`, `priority_class`) | Court, Receiver, Creditor |
| POST | `/v1/distribution-payments/{id}/pay` | Receiver pays a `SCHEDULED` distribution payment; OCC on the case version; senior-class gate | Receiver |
| POST | `/v1/distribution-payments/{id}/void` | Court voids a `PAID` payment; credits estate cash back | Court |
| POST | `/v1/_clock/set_current_utc` | Test-driving endpoint: sets the server's logical clock | SystemAdmin |

## 5. Error Code Catalogue

The trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the authoritative mapping of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_PLAN_NOT_EXECUTING` | 409 Conflict |
| `ERR_AUTHORIZATION_REQUIRED` | 409 Conflict |
| `ERR_AUTHORIZATION_MISMATCH` | 409 Conflict |
| `ERR_CLAIM_BARRED` | 422 Unprocessable Entity |
| `ERR_STATUS_REPORT_OVERDUE` | 422 Unprocessable Entity |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_GAP` | 409 Conflict |
| `ERR_FEE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_PLAN_ALREADY_OPEN` | 409 Conflict |
| `ERR_ENGAGEMENT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_UNDETERMINED_CLAIMS` | 409 Conflict |
| `ERR_DISCHARGE_BLOCKED` | 409 Conflict |
| `ERR_DUPLICATE_CASE_NUMBER` | 409 Conflict |
| `ERR_COLLATERAL_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SENIOR_CLASS_UNPAID` | 409 Conflict |
| `ERR_INSUFFICIENT_ESTATE_FUNDS` | 409 Conflict |
| `ERR_RESERVE_EXCEEDS_POOL` | 422 Unprocessable Entity |
| `ERR_FEE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_AMOUNT_EXCEEDS_REQUEST` | 422 Unprocessable Entity |
| `ERR_ALLOWED_EXCEEDS_FILED` | 422 Unprocessable Entity |
| `ERR_INTERNAL` | 500 Internal Server Error |
