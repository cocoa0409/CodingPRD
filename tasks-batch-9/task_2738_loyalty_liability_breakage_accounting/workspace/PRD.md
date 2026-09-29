# Loyalty Liability & Breakage Accounting API — Product Requirements Document

## 1. Introduction

Retail loyalty programmes create a real obligation the moment a point is handed out, and finance teams are expected to measure that obligation to the cent. Points issued today are a promise of future value; some of that promise will be redeemed, and some of it will quietly evaporate as members lose interest, move house, or let their balances lapse. The accounting treatment of that evaporation — **breakage** — is where loyalty finance becomes genuinely hard: the deferred revenue booked at issuance must be measured at the standalone selling price of a point, the share expected never to be redeemed must be estimated from cohort behaviour, and every subsequent re-estimation must be pushed back through the ledger as a catch-up adjustment rather than silently restated.

This document specifies the Loyalty Liability & Breakage Accounting API, the system of record for that measurement. It governs the whole chain: programme configuration and the standalone selling price of a point; enrolment cohorts carrying observed redemption patterns; point issuance with tier and promotional multipliers and the expense attribution those multipliers imply; redemption with first-in-first-out lot consumption, a provisional revenue release at allocation and a re-measured release at fulfilment; breakage estimates prepared by accountants, approved by controllers under segregation of duties, and superseded when a better estimate arrives; point expiry governed by state-by-state escheatment law; partner-issued and partner-redeemed point settlement across intercompany and third-party billing; and the modelling of proposed programme changes before they are allowed to touch live data.

Two design commitments run through every requirement below. First, **the ledger never drifts**: every operation that books an amount has an exact compensating path, so a reversed redemption, a reopened period or a superseded estimate returns the affected balances to the values they held before the operation. Second, **measurement is reproducible for audit**: figures that support a closed period or an actuarial memorandum are frozen snapshots, never re-derived from data that has moved on. Where those two commitments pull against convenience, the specification follows them.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint: authentication, response shape, pagination, the logical clock, the arithmetic conventions, resource identity, concurrency control, and the order in which the server rejects a bad request.

### 2.1. Actors, Headers and Role-Based Access Control

Every request — without exception, including reads — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. When either header is absent or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). When `X-User-Role` carries a value that is not one of the five recognised role names, the rejection is `ERR_UNKNOWN_ROLE` (HTTP 401). When the role is recognised but is not authorised for the endpoint being addressed, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The five roles are `ProgramAdmin`, `LoyaltyAccountant`, `Controller`, `PartnerOperator` and `Member`, and their division of labour is a segregation-of-duties model rather than a convenience hierarchy:

- A `ProgramAdmin` configures the programme — programme creation, activation, suspension and closure; state expiry rules; partner agreements and their termination; and the modelling of programme change orders. A `ProgramAdmin` never touches the ledger.
- A `LoyaltyAccountant` prepares the ledger — issuing point lots, allocating, fulfilling and reversing redemptions, running the expiry sweep, preparing and submitting breakage estimates, and creating, issuing and resolving partner settlement statements.
- A `Controller` approves and closes — approving and rejecting breakage estimates, opening, soft-closing, reopening and hard-closing accounting periods, paying and writing off settlement statements, and approving and applying programme change orders.
- A `PartnerOperator` is a third-party or intercompany partner acting on its own agreement. Its only write capability is disputing a statement issued against that agreement.
- A `Member` is a loyalty programme member acting on its own account. A member may request a redemption for itself and read its own record, lots and events; it never allocates, fulfils or measures anything.

Identity semantics differ by role and matter for ownership checks. When `X-User-Role` is `ProgramAdmin`, `LoyaltyAccountant` or `Controller`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a workflow demands attribution — as `prepared_by_user_id` when a `LoyaltyAccountant` creates a breakage estimate and as `approved_by_user_id` when a `Controller` approves one — but never compares it to any entity's `id`. When `X-User-Role` is `PartnerOperator`, `X-User-ID` is the `id` of the acting `PartnerAgreement`; ownership checks on any settlement statement compare the statement's `partner_agreement_id` to `X-User-ID`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on a member record, a point lot or a redemption event compare the resource's `member_id` (or, for the member record itself, its own `id`) to `X-User-ID`.

Ownership is enforced on exactly six operations: requesting a redemption, reading one member record, reading one point lot, reading one redemption event, reading one settlement statement, and disputing a settlement statement. In all six the rejection for an entity-backed role addressing something it does not own is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The opaque operator roles are never subject to this check — a `Controller` reading any member record is entirely in order.

Segregation of duties adds one further constraint that is independent of role membership: the `X-User-ID` that approves a breakage estimate must differ from the `X-User-ID` recorded as that estimate's `prepared_by_user_id`. Two distinct `Controller` users are perfectly acceptable; one human acting as both preparer and approver is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

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

### 2.3. Pagination and List Ordering

Every list read accepts two optional query parameters. `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` skips rows from the front of the ordered result and defaults to 0; negative values are not accepted. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

Unless a specific read says otherwise, list results are ordered by `created_at` ascending. The two allocation sub-resource reads are the exception: the ledger rows belonging to one point lot, and the ledger rows belonging to one redemption event, are both returned ordered by `allocation_seq` ascending and then by `created_at` ascending, because they are an append-only journal and their sequence is the point of reading them.

Each collection additionally accepts filters, and every filter is optional. Programmes may be filtered by `status` and by `breakage_method`. State expiry rules may be filtered by `program_id`, `state_code` and `expiry_permitted`. Cohorts may be filtered by `program_id` and `cohort_code`. Members may be filtered by `program_id`, `cohort_id`, `status`, `state_code` and `tier`. Accounting periods may be filtered by `program_id`, `state` and `period_code`. Partner agreements may be filtered by `program_id`, `partner_code`, `status` and `relationship_type`. Point lots may be filtered by `member_id`, `period_id`, `partner_agreement_id` and by either state dimension independently — `lifecycle_state` and `settlement_state`. Redemption events may be filtered by `member_id`, `period_id`, `partner_agreement_id`, `state` and `redemption_type`. Breakage estimates may be filtered by `program_id`, `period_id`, `cohort_id`, `supersedes_estimate_id`, `state` and `method_applied`. Settlement statements may be filtered by `partner_agreement_id`, `period_id`, `state` and `settlement_basis`. Programme change orders may be filtered by `program_id`, `change_type`, `state` and `cancelled_by_order_id`. Both allocation sub-resource reads accept `entry_type` to isolate the original consumption rows from the compensating rows.

A `PartnerOperator` listing settlement statements sees only the statements of the agreement it acts as; a `PartnerOperator` reading one agreement may read only the agreement it acts as.

### 2.4. The Logical Clock and Calendar Arithmetic

Nothing in this system reads the machine's wall clock. Every timestamp comparison — expiry eligibility, period-end tests, change-order effectiveness, dormancy measurement — reads a server-held **logical UTC clock**. At server startup that clock reads exactly `2026-08-01T00:00:00Z`, and it must continue to read that instant until it is explicitly moved; falling back to real time is a defect. A test-driving capability, available to `ProgramAdmin`, `LoyaltyAccountant` and `Controller` alike, sets the clock to a supplied `current_utc` instant. Setting the clock mutates no entity and bumps no `version`.

Calendar arithmetic is always in whole days on that logical clock. When a lot's expiry horizon is described as a number of days after issuance, or a statement's due date as a number of days after a period ends, the computation adds that many 24-hour days to the base instant. There is no calendar-month arithmetic anywhere in this specification.

Instant comparisons are inclusive wherever a boundary is stated as "on or after". A point lot whose `expires_at` is `2028-08-04T00:00:00Z` is not yet expirable when the clock reads `2028-08-03T23:59:59.999Z`, and becomes expirable at exactly `2028-08-04T00:00:00Z`. The same inclusive reading governs soft-close (permitted once the clock reaches the period's `end_at`, not before) and change-order application (permitted once the clock reaches the order's `effective_at`).

Two window conventions coexist and must not be confused. An accounting period's window runs from `start_at` inclusive to `end_at` exclusive — a half-open interval, so two periods that merely touch at an instant do not overlap. A cohort's enrolment window (`enrollment_start_date` through `enrollment_end_date`) and a partner agreement's effective window (`effective_start_date` through `effective_end_date`) are closed intervals, inclusive at both ends. In all three cases the end must fall strictly after the start.

### 2.5. Money in Integer Cents, Rates in Basis Points, and the Rounding Discipline

No floating-point value is ever persisted or returned by this API. Four unit conventions apply everywhere:

- **Cents.** Every monetary amount is an integer number of cents. Field names ending in `_cents` are integers, and negative values are meaningful where the specification says so (a partner may be owed money; a liability may need topping up).
- **Millicents per point.** The standalone selling price of a single point, and the partner issuance and redemption rates, are expressed in thousandths of a cent per point. A value of 1200 means 1.200 cent per point; a value of 1500 means 1.500 cent per point. Converting a point count priced in millicents into cents therefore divides by 1000.
- **Basis points.** Every rate, multiplier and elasticity is expressed in basis points, where 10000 basis points is exactly 1.0000 and 2500 basis points is exactly one quarter. Converting a basis-point rate into a fraction therefore divides by 10000.
- **Whole points.** Point counts are integers.

Rounding is uniform: every division named in this document is followed by rounding to a whole number using the round-half-up rule — a remainder of exactly one half rounds away from zero, upward in magnitude. The arithmetic must be carried out on exact rational or decimal values and rounded once at each point the specification names, never approximated through binary floating point.

Where the specification names two consecutive roundings, both roundings are mandatory and the second consumes the first's already-rounded result. Collapsing a two-step rounded computation into a single multiply-then-round changes the answer whenever both factors carry a fractional tail, and the collapsed answer is wrong. The same applies to sums: where a total is described as a per-row or per-lot amount rounded first and then added up, the rounding happens before the addition, not after.

### 2.6. Resource Identity, Audit Fields and Derived Reads

Every resource carries a server-minted `id` — a UUID string with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits. Programmes, state expiry rules, cohorts, members, accounting periods, partner agreements, point lots, redemption events, breakage estimates, settlement statements and programme change orders additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on each mutation of that resource.

`RedemptionAllocation` rows are the exception. They are append-only journal entries that are never modified after they are written, so they carry only `id` and `created_at`: both `updated_at` and `version` are absent from a `RedemptionAllocation` altogether.

A distinction that recurs throughout §3 is between **persisted** figures and figures that are **derived on read**. A persisted figure is written by an operation, counts as a mutation of its resource, and therefore refreshes `updated_at` and increments `version`. A derived-on-read figure is recomputed from current data every time the resource is read and is never stored; reading it does not refresh `updated_at` and does not increment `version`. The derived-on-read figures are a programme's `total_deferred_revenue_cents` and `recognized_breakage_ytd_cents`; a member's `dormancy_days`, `point_balance` and `outstanding_gross_ssp_cents`; and a point lot's `remaining_gross_ssp_cents` and `remaining_deferred_cents`. Every other figure named in this document is persisted.

Where a nested path is addressed, path identifiers are resolved strictly left to right and the first identifier that does not resolve decides the 404. A request naming a programme that does not exist fails with `ERR_PROGRAM_NOT_FOUND` before any later segment is examined. Each entity has its own not-found code — `ERR_PROGRAM_NOT_FOUND`, `ERR_STATE_EXPIRY_RULE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_PARTNER_AGREEMENT_NOT_FOUND`, `ERR_POINT_LOT_NOT_FOUND`, `ERR_REDEMPTION_EVENT_NOT_FOUND`, `ERR_BREAKAGE_ESTIMATE_NOT_FOUND`, `ERR_SETTLEMENT_STATEMENT_NOT_FOUND` and `ERR_CHANGE_ORDER_NOT_FOUND` — and each carries HTTP 404. Foreign keys supplied in a request body are resolved after every path segment has resolved, and among themselves they are resolved in the order the endpoint declares its input fields.

### 2.7. Optimistic Concurrency on Programme and Agreement Snapshots

Two operations are guarded by optimistic concurrency control, because in both cases a repeated operation is a legitimate product action rather than an invalid-state error, and only a version check can tell a deliberate second write from a write built on a stale read.

Approving a breakage estimate requires the request to carry `expected_program_version`, holding the `version` of the parent `LoyaltyProgram` as the approving `Controller` last observed it. This field is not optional. If it does not equal the programme's current `version`, the approval is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). Approval legitimately overwrites the programme's `current_breakage_rate_bp` and retires the reigning approved estimate, so a second approval of a different submitted estimate would itself succeed; the stale-version check is what stops a controller from installing a rate derived from a programme snapshot that a prior approval, an applied change order or an expiry sweep has already invalidated.

Creating a settlement statement requires the request to carry `expected_partner_agreement_version`, holding the `version` of the parent `PartnerAgreement` as the accountant last observed it. This field is not optional. If it does not equal the agreement's current `version`, the create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). A new statement legitimately supersedes any existing draft statement for the same agreement-and-period pair, so a second create is a valid operation; the stale-version check is what stops a statement from being measured against an agreement snapshot that a subsequent partner-issued lot, a partner redemption allocation or a prior statement has already moved.

No other endpoint accepts a version field, and no other endpoint performs a version check. Neither of these two checks depends on requests overlapping in time: the rejection is a function of the version value supplied versus the version value stored, nothing more.

### 2.8. The Validation Ladder

Any single request may violate several rules at once. The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported. The ordering is normative — two of its steps are deliberately placed to make a specific pairing come out one way rather than the other.

1. **Header presence** — `ERR_MISSING_AUTH_HEADERS` (401), on every endpoint.
2. **Role recognition** — `ERR_UNKNOWN_ROLE` (401), on every endpoint.
3. **Role authorisation** — `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint.
4. **Resource ownership for entity-backed roles** — `ERR_NOT_RESOURCE_OWNER` (403), on redemption request, single-member read, single-lot read, single-event read, single-statement read and statement dispute.
5. **Request shape** — the body parses, every required input the endpoint declares is present, every value satisfies its declared type, enumeration and range constraint, and pagination parameters are in range. Otherwise `ERR_INVALID_REQUEST` (400), on every endpoint.
6. **Path existence, left to right** — the relevant not-found code from §2.6 (404), on every endpoint carrying an identifier in its path.
7. **Body foreign-key existence, in declared input order** — the relevant not-found code from §2.6 (404), on state-expiry-rule create, cohort create, member enrolment, period create, partner-agreement create, point-lot issuance, redemption request, breakage-estimate create, statement create and change-order create.
8. **Programme version match** — `ERR_STALE_PROGRAM_VERSION` (412), on estimate approval. This sits above every state check, so a stale approval is reported as 412 even when the estimate is also in the wrong state.
9. **Agreement version match** — `ERR_STALE_AGREEMENT_VERSION` (412), on statement create.
10. **Addressed period is `OPEN`** — `ERR_PERIOD_NOT_OPEN` (409), on point-lot issuance, redemption request, redemption allocation, redemption fulfilment, redemption reversal, breakage-estimate create, estimate submit, estimate approve and the expiry sweep.
11. **Owning programme is `ACTIVE`** — `ERR_PROGRAM_NOT_ACTIVE` (409), on point-lot issuance, redemption request, redemption allocation, breakage-estimate create, change-order approve and change-order apply.
12. **Current state is a legal source state for the requested transition** — `ERR_INVALID_STATE_TRANSITION` (409), on every action endpoint that drives a state machine. This covers every attempt to leave a terminal state and every repeat of an action already performed.
13. **Addressed agreement is `ACTIVE`** — `ERR_AGREEMENT_NOT_ACTIVE` (409), on statement create and statement issue.
14. **Addressed period is not `HARD_CLOSED`** — `ERR_PERIOD_HARD_CLOSED` (409), on period reopen, statement create, statement issue, statement pay and statement write-off. No child of a hard-closed period may be mutated.
15. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (409), on estimate approval.
16. **Actuarial memorandum on file** — `ERR_MEMO_NARRATIVE_REQUIRED` (409), on hard-close.
17. **An approved estimate exists** — `ERR_ESTIMATE_NOT_APPROVED` (409), on soft-close and on redemption fulfilment.
18. **No redemption of the period is still merely requested** — `ERR_UNALLOCATED_REDEMPTIONS` (409), on soft-close.
19. **Window sanity** — `ERR_INVALID_WINDOW` (409), on period create and partner-agreement create.
20. **Period windows do not overlap** — `ERR_PERIOD_OVERLAP` (409), on period create.
21. **Partner windows do not conflict** — `ERR_PARTNER_WINDOW_CONFLICT` (409), on partner-agreement create.
22. **Period window has elapsed** — `ERR_PERIOD_NOT_ENDED` (409), on soft-close.
23. **Change order has reached its effective instant** — `ERR_CHANGE_NOT_YET_EFFECTIVE` (409), on change-order apply.
24. **Period belongs to the same programme as its counterparty** — `ERR_PERIOD_PROGRAM_MISMATCH` (409), on point-lot issuance, redemption request, breakage-estimate create and statement create.
25. **Cohort belongs to the same programme** — `ERR_COHORT_PROGRAM_MISMATCH` (409), on member enrolment and breakage-estimate create.
26. **Partner agreement belongs to the same programme** — `ERR_AGREEMENT_PROGRAM_MISMATCH` (409), on point-lot issuance, redemption request and statement create.
27. **Codes are unique within their programme** — `ERR_DUPLICATE_CODE` (409), on period create, cohort create, state-expiry-rule create and member enrolment.
28. **Tier multiplier keys are exactly the four tiers** — `ERR_TIER_MULTIPLIER_KEYS_INVALID` (409), on programme create and change-order create.
29. **Every statement of the period is settled** — `ERR_UNSETTLED_STATEMENTS` (409), on hard-close.
30. **Bounded-cycle budgets** — `ERR_REVISION_LIMIT_EXCEEDED` on estimate resubmission, `ERR_REOPEN_LIMIT_EXCEEDED` on period reopen, `ERR_DISPUTE_LIMIT_EXCEEDED` on statement dispute, each HTTP 409.
31. **Sensitivity band straddles the measured rate** — `ERR_SENSITIVITY_BAND_INVALID` (409), on breakage-estimate create.
32. **Promotional multiplier within the programme cap** — `ERR_PROMO_MULTIPLIER_ABOVE_CAP` (409), on point-lot issuance.
33. **Agreement balance cleared before termination** — `ERR_OUTSTANDING_SETTLEMENT` (409), on partner-agreement terminate. Sharing this rung, and applying to a disjoint operation so no ambiguity arises: **every period hard-closed before programme closure** — `ERR_PERIODS_NOT_CLOSED` (409), on programme close.
34. **Issuance cap respected** — `ERR_ISSUANCE_CAP_EXCEEDED` (409), on point-lot issuance.
35. **Member balance sufficient** — `ERR_INSUFFICIENT_POINT_BALANCE` (409), on redemption allocation.
36. **Estimate has something to measure** — `ERR_NO_OUTSTANDING_POINTS` (409), on breakage-estimate create.
37. **Programme configuration complete** — `ERR_PROGRAM_CONFIG_INCOMPLETE` (409), on first programme activation.

Two consequences of this ordering are deliberate and worth stating explicitly. Issuing a point lot into a period that is no longer `OPEN`, with a point count that would also breach the programme's per-issuance cap, is reported as `ERR_PERIOD_NOT_OPEN` — the period-state rung sits above the fiscal-cap rung. And hard-closing a period whose approved estimate carries an empty actuarial memorandum while a statement of that period is also still unsettled is reported as `ERR_MEMO_NARRATIVE_REQUIRED` — the memorandum rung sits above the settlement rung.

### 2.9. Cascade Discipline and Hierarchical Consistency

Many operations in this system touch more than one resource. A cascade is not a best-effort convenience: where §3 states that an operation also mutates a parent, a sibling or a set of children, those mutations are part of the operation and each of them independently refreshes the affected resource's `updated_at` and increments its `version`.

Cascades are also **ordered**, and where a cascade fans out over a collection the traversal order is specified because it is observable in the resulting `version` numbers and journal sequence. Lots consumed by a redemption are walked in issuance order; lots swept for expiry are walked in issuance order; lots settled or written off by a statement are walked in creation order; cohorts adjusted by an applied change order are walked by enrolment start and then creation; competing change orders are cancelled in creation order; members evaluated for dormancy are walked in creation order.

Some cascades are chains, where a later link is caused by an earlier link's completion rather than by the original request. Expiry causes escheatment where state law requires it, and the escheat accrual in turn causes the programme's disclosure latch to flip. Estimate approval installs a new programme rate, the new rate retires the reigning estimate, and retiring that estimate forces its supporting period back open. Applying a change order writes the new parameter onto the programme, the new expiry horizon re-dates outstanding lots, and the changed horizon shifts every cohort's behavioural adjustment. §3 names each link; all of them fire within the single request that started the chain.

Finally, a hard-closed accounting period is immutable, and so is everything beneath it. Once a period reaches `HARD_CLOSED`, no mutation of that period or of any statement belonging to it is permitted, and the attempt is rejected with `ERR_PERIOD_HARD_CLOSED`.

### 2.10. Bounded Correction Cycles

This system deliberately permits a small number of loops rather than forcing an irreversible path, because accounting corrections are normal. Each loop has a hard budget of two, tracked by a counter that only ever goes up.

A rejected breakage estimate may be revised and resubmitted while its `revision_count` is below 2, and each resubmission after a rejection increments that counter; a third resubmission is rejected with `ERR_REVISION_LIMIT_EXCEEDED`. A soft-closed period may be reopened by a `Controller` while its `reopen_count` is below 2, and each reopen increments that counter; a third manual reopen is rejected with `ERR_REOPEN_LIMIT_EXCEEDED`. An issued statement may be disputed by its partner while its `dispute_count` is below 2, and each dispute increments that counter; a third dispute is rejected with `ERR_DISPUTE_LIMIT_EXCEEDED`. None of the three counters is ever reset — not by a resolution, not by a reopen, not by any other operation.

One case is exempt from a budget while still consuming it: the forced reopen described in §3.6, which the system performs when an estimate backing a soft-closed period is superseded, is not gated on `reopen_count` at all — the accounting rule that a close must rest on a live approved estimate outranks the manual reopen budget — yet it still increments `reopen_count`, so it eats into what a `Controller` can do manually afterwards.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Loyalty Programme

A `ProgramAdmin` begins by registering a **LoyaltyProgram**, the aggregate root under which every cohort, member, period, agreement, estimate and change order lives. The programme is created with a display `name` of at most 120 characters that may not be empty, and with a `currency_code` naming the reporting currency of the deferred-revenue ledger as exactly three uppercase letters; when the caller omits it, the currency is `USD`. The economic heart of the configuration is `ssp_millicents_per_point`, the standalone selling price of one point in thousandths of a cent, accepted anywhere from 1 through 100000 inclusive. This price is snapshotted onto every lot at issuance, so changing it later never re-prices points already handed out.

Three further parameters bound issuance. `point_expiry_days`, between 1 and 3650 inclusive, is the number of whole days a lot survives after issuance. `per_issuance_point_cap`, at least 1, is the largest point count a single lot may carry once tier and promotional multipliers have been applied; the boundary is inclusive, so a lot whose measured point count lands exactly on the cap is accepted and only a strictly larger count is rejected with `ERR_ISSUANCE_CAP_EXCEEDED`. `tier_multiplier_bp` is an object of earn multipliers in basis points keyed by member tier, and it must declare exactly the four keys `BASE`, `SILVER`, `GOLD` and `PLATINUM` — no more, no fewer — each value an integer from 10000 through 50000 inclusive. A key set that is not exactly those four is rejected with `ERR_TIER_MULTIPLIER_KEYS_INVALID`. Promotional generosity is capped separately by `promo_multiplier_cap_bp`, which defaults to 30000 and is accepted from 10000 through 100000 inclusive.

Breakage methodology is chosen at configuration time. `breakage_method` is either `COHORT_WEIGHTED` or `PROGRAM_HISTORICAL` and defaults to `COHORT_WEIGHTED`. Alongside it, `historical_redemption_rate_bp` — from 200 through 9800 inclusive — records the programme-level redemption rate observed to date; it is consumed directly by the programme-historical measurement and it is also what seeds the programme's live breakage rate at first activation. Escheatment disclosure is governed by `escheat_disclosure_threshold_cents`, a non-negative amount defaulting to 100000 cents, which is one thousand currency units.

A freshly created programme is born in status `DRAFT`, with `current_breakage_rate_bp` at 0, `total_escheat_accrual_cents` at 0, `escheat_disclosure_required` false, and `version` at 1. Two figures on the programme are never stored. `total_deferred_revenue_cents` is the sum, over this programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, of each lot's `remaining_deferred_cents`. `recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`. Both are recomputed on each read and reading them never bumps the programme's `version`.

Before a programme may go live it needs its expiry policy and at least one enrolment vintage. Expiry policy is expressed per US state as a **StateExpiryRule** attached to a programme through a `program_id` and identified by a `state_code` of exactly two uppercase letters; the combination of programme and state code must be unique, and a repeat is rejected with `ERR_DUPLICATE_CODE`. Each rule declares `expiry_permitted`: when false, no lot held by a member resident in that state may ever reach `EXPIRED`, no matter how far past its expiry horizon the clock has run. It declares `min_dormancy_days`, from 0 through 3650 inclusive, which a member's dormancy must reach — the comparison is inclusive — before that member's lots become expirable. It declares `escheatment_required`: when true, a lot that reaches `EXPIRED` continues immediately to `ESCHEATED` and accrues escheat liability to the state. And it declares `escheat_rate_bp`, the escheatable fraction of the expired lot's gross standalone selling price, defaulting to 10000 basis points — the whole amount — and accepted from 0 through 10000 inclusive.

Enrolment vintages are **Cohort** rows, each attached to a programme through a `program_id` and labelled by a `cohort_code` of at most 32 non-empty characters that must be unique within the programme, again on pain of `ERR_DUPLICATE_CODE`. A cohort's enrolment window is the closed interval from `enrollment_start_date` through `enrollment_end_date`, and the end must fall strictly after the start. Behaviourally, a cohort carries `observed_redemption_rate_bp` — the redemption rate historically observed for that vintage before any programme-change effect, from 0 through 10000 inclusive — and `sample_size`, the number of members underlying that observation, at least 1. `sample_size` is recorded for the actuarial memorandum and is deliberately not an input to any formula in this document. A cohort also carries `program_change_adjustment_bp`, a signed behavioural adjustment from -5000 through 5000 inclusive that defaults to 0 and is moved only by an applied programme change order.

Members are enrolled by either a `ProgramAdmin` or a `LoyaltyAccountant` into a named cohort of a named programme, supplying `program_id`, `cohort_id`, an `external_member_ref` of at most 64 non-empty characters, a `state_code` of exactly two uppercase letters giving the state of residence that selects the governing expiry rule, and a `tier` of `BASE`, `SILVER`, `GOLD` or `PLATINUM` — `BASE` when omitted. The `external_member_ref` must be unique within the programme (`ERR_DUPLICATE_CODE` otherwise), and the named cohort must belong to the same programme as the one named in the body, else `ERR_COHORT_PROGRAM_MISMATCH`. A new member is born with `status` `ACTIVE`, with `enrolled_at` set to the current logical clock reading, and with `last_activity_at` initialised to that same instant. Three member figures are derived on read: `dormancy_days` is the whole number of days between `last_activity_at` and the current clock reading, computed by dividing the elapsed seconds by 86400 and discarding the fraction, and floored at 0; `point_balance` is the sum of `points_remaining` over the member's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`; and `outstanding_gross_ssp_cents` is the sum, over that same set of lots, of each lot's `remaining_gross_ssp_cents`, with each lot rounded first and the rounded amounts then added.

Activation is a `ProgramAdmin` action and has two distinct forms that share one entry point. The first activation moves the programme `DRAFT → ACTIVE`, and it is permitted only when the programme already has at least one state expiry rule and at least one cohort; a programme missing either is rejected with `ERR_PROGRAM_CONFIG_INCOMPLETE`. That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`. It also increments the programme's `version` by 1. The second form is reactivation, `SUSPENDED → ACTIVE`, which explicitly does **not** reseed the rate — `current_breakage_rate_bp` is left exactly as the most recent estimate approval left it — and increments `version` by 1. Suspension, `ACTIVE → SUSPENDED`, likewise increments `version` by 1; it blocks issuance and redemption while leaving period close and partner settlement fully available. Closure moves the programme `ACTIVE → CLOSED` or `SUSPENDED → CLOSED`, increments `version` by 1, and is permitted only when every accounting period of the programme has reached `HARD_CLOSED`; otherwise the attempt is rejected with `ERR_PERIODS_NOT_CLOSED`. `CLOSED` is terminal. Issuance, redemption, estimate preparation and settlement all require the programme to be `ACTIVE`, and an attempt against a programme in any other status is rejected with `ERR_PROGRAM_NOT_ACTIVE`.

### 3.2. The Accounting Calendar

Only a `Controller` opens an **AccountingPeriod**. The request names the owning programme through `program_id`, a reporting label as `period_code` of at most 16 non-empty characters such as "2026-08", and the window boundaries `start_at` and `end_at`. The label must be unique within the programme, else `ERR_DUPLICATE_CODE`. The window is half-open: `start_at` belongs to the period and `end_at` does not. The end must fall strictly after the start; a window whose start is at or after its end is rejected with `ERR_INVALID_WINDOW`. The new window must not overlap any existing period of the same programme, and a violation is `ERR_PERIOD_OVERLAP` — but because the interval is half-open, a window that begins at exactly the instant another window ends is adjacent rather than overlapping and is accepted, and gaps between windows are permitted too.

A new period is born in `state` `OPEN`, with `reopen_count` at 0, with `soft_closed_at` null, and with all eleven of its currency and rate rollforward figures at 0: `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `escheat_accrual_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp`.

Five of those figures are **movement accumulators** maintained incrementally as the period lives, not computed at close. `issuance_deferred_cents` grows by each issued lot's `deferred_revenue_cents`. `redemption_recognized_cents` grows by a redemption event's `provisional_release_cents` when that event is allocated and shrinks by the same amount when the event is reversed. `remeasurement_delta_cents` grows by an event's own `remeasurement_delta_cents` at fulfilment and shrinks by the same amount on reversal. `expiry_released_cents` grows by the deferral released whenever the sweep expires a lot into this period. `escheat_accrual_cents` grows by each escheated lot's `escheated_cents`. The remaining figures are written only by a close and reset only by a reopen, as §3.7 describes.

Whether a period accepts work depends on its `state`. Issuing a lot, requesting a redemption, allocating, fulfilling or reversing one, preparing an estimate, submitting an estimate, approving an estimate and running the expiry sweep all require the addressed period to be `OPEN`; against a `SOFT_CLOSED` or `HARD_CLOSED` period each of these is rejected with `ERR_PERIOD_NOT_OPEN`. Separately, and at a lower rung of the ladder, no child of a `HARD_CLOSED` period may be mutated at all: reopening the period, or creating, issuing, paying or writing off one of its statements, is rejected with `ERR_PERIOD_HARD_CLOSED`. Whenever a period named in a request body must pair with a member, a partner agreement or a programme, it must belong to the same programme as its counterparty, and a cross-programme pairing is rejected with `ERR_PERIOD_PROGRAM_MISMATCH`.

### 3.3. Issuing Points: Tier Uplift, Promotional Uplift and Deferred Revenue

Point issuance is exclusively a `LoyaltyAccountant` action, and it is where the liability is born. The request names the holder through `member_id` and the period the issuance books to through `period_id`, optionally names a partner through `partner_agreement_id` (absent or null for programme-issued points), supplies `base_points` of at least 1, and may supply `promo_multiplier_bp`, a promotional multiplier of at least 10000 basis points that defaults to 10000 — meaning no promotion. A promotional multiplier above the programme's `promo_multiplier_cap_bp` is rejected with `ERR_PROMO_MULTIPLIER_ABOVE_CAP`. When a partner is named, that agreement must belong to the same programme as the member, else `ERR_AGREEMENT_PROGRAM_MISMATCH`; the named period must likewise belong to that programme, else `ERR_PERIOD_PROGRAM_MISMATCH`.

Issuance first freezes four values onto the new **PointLot** and never revisits them. `tier_multiplier_bp_at_issue` takes the programme's `tier_multiplier_bp` entry for the member's current `tier`. `ssp_millicents_per_point_at_issue` takes the programme's `ssp_millicents_per_point`; it is immutable thereafter, so a later change of the programme's standalone selling price leaves this lot priced as it was issued. `breakage_rate_bp_at_issue` takes the programme's `current_breakage_rate_bp` as it stands at this instant. `issued_at` takes the current logical clock reading, and `expires_at` is set to `issued_at` advanced by the programme's `point_expiry_days` whole days.

Measurement then proceeds in a fixed sequence, and the sequence matters because two of its steps round.

- **Tier uplift.** `tier_points` is `base_points` multiplied by `tier_multiplier_bp_at_issue`, divided by 10000, and rounded half up to a whole number of points. For a `BASE` member whose multiplier is exactly 10000 basis points this step is an identity on `base_points`.
- **Promotional uplift.** `points_issued` is the **already-rounded** `tier_points` multiplied by `promo_multiplier_bp`, divided by 10000, and rounded half up again. These are two separate roundings and the second consumes the first's rounded output; `points_issued` is never obtained in one shot from `base_points` by multiplying both multipliers together before rounding, because that produces a different whole number whenever both multipliers carry a fractional tail. When `promo_multiplier_bp` is the default 10000, this step is an identity on `tier_points`.
- **Opening balance.** `points_remaining` starts equal to `points_issued`.
- **Gross standalone selling price.** `gross_ssp_cents` is `points_issued` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up.
- **Reserve and deferral.** `breakage_reserve_cents` is `gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up. `deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`.
- **Expense attribution.** The two uplifts are expensed separately, each measured on its own point delta at the snapshotted price. `tier_benefit_expense_cents` is the difference between `tier_points` and `base_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up — and is therefore 0 for a `BASE` member. `promo_expense_cents` is the difference between `points_issued` and `tier_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up.

Only once `points_issued` has been measured is the cap tested: a `points_issued` strictly greater than the programme's `per_issuance_point_cap` is rejected with `ERR_ISSUANCE_CAP_EXCEEDED`, and a value exactly equal to the cap passes.

Two remainder figures are recomputed on every read of the lot rather than stored. `remaining_gross_ssp_cents` is `points_remaining` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up. `remaining_deferred_cents` is that remaining gross less the reserve on the remaining gross — that is, less `remaining_gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up. Both are the running measure of how much of this lot's promise is still owed.

Issuance also refreshes the member and, where relevant, the partner. `last_activity_at` on the holder is set to the current clock reading. If that member was `DORMANT`, the issuance revives it: the member moves `DORMANT → ACTIVE`, and the member's `version` increments by 1. When the request carried a `partner_agreement_id`, the named agreement's `version` increments by 1, because a partner-issued lot changes what the next settlement statement will measure.

A lot carries **two independent state dimensions on one row**, and neither is a precondition of the other. The redemption-and-expiry dimension, `lifecycle_state`, is born `OUTSTANDING` and may reach `PARTIALLY_REDEEMED`, `FULLY_REDEEMED`, `EXPIRED` or `ESCHEATED`. The partner-billing dimension, `settlement_state`, is born `NOT_APPLICABLE` when no partner was named, and is born `PENDING_SETTLEMENT` when one was — the dimension-two assignment `NOT_APPLICABLE → PENDING_SETTLEMENT` happens at creation, so a partner lot is born `PENDING_SETTLEMENT` on one dimension while being born `OUTSTANDING` on the other. From `PENDING_SETTLEMENT` a lot may reach `SETTLED` or `WRITTEN_OFF`, as §3.5 describes. The independence is real and testable: an `OUTSTANDING` lot may be `SETTLED`, and a `FULLY_REDEEMED` lot may still be `PENDING_SETTLEMENT`. `ESCHEATED` and `WRITTEN_OFF` are the terminal values of their respective dimensions.

### 3.4. Redemption: Request, Allocation, Fulfilment and Reversal

A redemption begins as a request, which either a `LoyaltyAccountant` or the `Member` itself may raise; a `Member` may raise one only for its own account, and addressing another member's account is rejected with `ERR_NOT_RESOURCE_OWNER`. The request names `member_id` and `period_id`, may name `partner_agreement_id` when the points are being burnt at a partner, and supplies `points_requested` of at least 1 together with a `redemption_type` of `CATALOG`, `PARTNER` or `CASH_BACK`. A `redemption_type` of `PARTNER` requires a non-null `partner_agreement_id`. The new **RedemptionEvent** is born in `state` `REQUESTED` with `requested_at` set to the clock reading, `allocated_at` null, `reversal_reason` null, and its four monetary figures — `provisional_release_cents`, `final_release_cents`, `remeasurement_delta_cents` and `partner_cost_cents` — all at 0. No revenue is released by the request itself.

**Allocation** — a `LoyaltyAccountant` action that moves the event `REQUESTED → ALLOCATED` — is where lots are consumed. It requires the event to be `REQUESTED`, the member's programme to be `ACTIVE`, the event's period to be `OPEN`, and the member's outstanding balance to be sufficient: the sum of `points_remaining` over the member's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` must be at least `points_requested`, and a strictly smaller balance is rejected with `ERR_INSUFFICIENT_POINT_BALANCE`.

Consumption is first-in-first-out. The candidate lots are the member's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` and whose `points_remaining` is greater than zero; lots that are `FULLY_REDEEMED`, `EXPIRED` or `ESCHEATED` are never consumed, regardless of their `settlement_state`. The candidates are walked in order of `issued_at` ascending and then `created_at` ascending — never by identifier — so a lot recorded later but carrying an earlier issuance instant is still consumed first. From each lot in turn the allocation draws the lesser of the points still needed and that lot's `points_remaining`, until `points_requested` is exhausted.

Each consumed lot produces exactly one **RedemptionAllocation** row, an append-only journal entry that names its `redemption_event_id` and its `point_lot_id`, carries `entry_type` `ALLOCATION`, and is numbered by `allocation_seq` starting at 1 and increasing by 1 in consumption order. The row records `points_allocated`, the positive count drawn from that lot, and `line_gross_ssp_cents`, being `points_allocated` multiplied by that lot's `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up. It also records `provisional_release_cents` for the line: the line's gross less the reserve on that line, where the reserve is the line gross multiplied by **that lot's own** `breakage_rate_bp_at_issue`, divided by 10000, rounded half up. The row's `final_release_cents` stays null until the event is fulfilled. The event's own `provisional_release_cents` is the sum of the per-line provisional releases — each line rounded first, then the rounded amounts added. Because the rate used is each lot's own frozen snapshot, a redemption spanning lots issued under different breakage rates blends several rates within one event. The deduction is always per line; deducting one reserve from the summed gross instead is wrong.

Allocation drives each consumed lot's `lifecycle_state`. A lot that was `OUTSTANDING` and gives up a positive count strictly fewer than its `points_remaining` moves `OUTSTANDING → PARTIALLY_REDEEMED`, with `points_remaining` decremented by the amount drawn, one `ALLOCATION` row appended, and the lot's `version` incremented by 1. A lot that was `OUTSTANDING` and gives up exactly its `points_remaining` moves `OUTSTANDING → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1. A lot that was already `PARTIALLY_REDEEMED` and gives up exactly its `points_remaining` moves `PARTIALLY_REDEEMED → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1; if it gives up less than that, it remains `PARTIALLY_REDEEMED` with its balance reduced.

The allocation also sets `allocated_at` to the clock reading and measures the partner cost leg, which is independent of the revenue legs: when the event names a `partner_agreement_id`, `partner_cost_cents` is `points_requested` multiplied by that agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up; when no partner is named it is 0. The event's `provisional_release_cents` is added to the period's `redemption_recognized_cents`. When the event names a partner, that agreement's `version` increments by 1. The event's own `version` increments by 1.

**Fulfilment** — also a `LoyaltyAccountant` action — moves the event `ALLOCATED → FULFILLED` and re-measures the same lines at the programme's current view of breakage. It requires the event to be `ALLOCATED`, its period to be `OPEN`, and an `APPROVED` breakage estimate to exist for that period; without one the attempt is rejected with `ERR_ESTIMATE_NOT_APPROVED`. For every `ALLOCATION` row of the event, `final_release_cents` is written as the row's `line_gross_ssp_cents` less the reserve on that line computed at the **single** current programme rate — the line gross multiplied by the programme's `current_breakage_rate_bp`, divided by 10000, rounded half up — ignoring the per-lot snapshots entirely. The event's `final_release_cents` is the sum of those per-line finals, each rounded before being added, and the event's `remeasurement_delta_cents` is `final_release_cents` less `provisional_release_cents`. That delta is added to the period's `remeasurement_delta_cents`, separately from the provisional release already booked. The event's `version` increments by 1. No lot balance moves at fulfilment.

**Reversal** is the compensating action, available to a `LoyaltyAccountant` from either `ALLOCATED → REVERSED` or `FULFILLED → REVERSED`, and it requires the event's period to be `OPEN`. The request carries a free-text `reversal_reason`, which is stored on the event. For every `ALLOCATION` row of the event, walked in ascending `allocation_seq` order, one compensating row is appended with `entry_type` `REVERSAL` and the same `allocation_seq` ordering, carrying `points_allocated`, `line_gross_ssp_cents` and `provisional_release_cents` as the exact negations of the original row's values, and — when the event had been fulfilled — `final_release_cents` negated as well. Nothing is re-measured on reversal: the negated values are copied from the original rows, which is what makes the compensation exact.

Each consumed lot has its `points_remaining` restored by the reversed count and its `lifecycle_state` driven back, with its `version` incremented by 1 in each case. A `FULLY_REDEEMED` lot that has strictly fewer points restored than its `points_issued` moves `FULLY_REDEEMED → PARTIALLY_REDEEMED`. A `FULLY_REDEEMED` lot that has exactly its `points_issued` restored moves `FULLY_REDEEMED → OUTSTANDING`, with `points_remaining` set back to `points_issued`. A `PARTIALLY_REDEEMED` lot whose `points_remaining` equals `points_issued` after the restoration moves `PARTIALLY_REDEEMED → OUTSTANDING`. Note that `points_issued` is never touched by any of this, which is precisely why the journal invariant holds at every instant: the sum of `points_allocated` across all of a lot's rows equals that lot's `points_issued` less its `points_remaining`.

On the ledger side, reversal subtracts the event's `provisional_release_cents` from the period's `redemption_recognized_cents`, and — when the event had been fulfilled — also subtracts the event's `remeasurement_delta_cents` from the period's `remeasurement_delta_cents`. Both legs are unwound, so the two period accumulators return to their exact pre-allocation values with no drift. `REVERSED` is terminal for the event, and the event's `version` increments by 1.

The journal is readable from either side. The rows that consumed or restored one lot can be read as a sub-resource of that lot, and the rows belonging to one event can be read as a sub-resource of that event; both reads accept `entry_type` as a filter so an auditor can look at the original consumption alone or the compensating entries alone, and both return rows ordered by `allocation_seq` ascending then `created_at` ascending.

### 3.5. Partner Economics: Agreements, Statements and the Dispute Cycle

Partners both cause points to be issued and accept points in redemption, and both directions are billable. A `ProgramAdmin` registers a **PartnerAgreement** under a programme named by `program_id`, identified by a `partner_code` of at most 32 non-empty characters, and typed by `relationship_type`: `INTERCOMPANY`, which settles through the intercompany ledger, or `THIRD_PARTY`, which settles through external billing. The two economics are `issuance_rate_millicents_per_point`, the thousandths of a cent the partner owes the programme for each point the partner causes to be issued, and `redemption_rate_millicents_per_point`, the thousandths of a cent the programme owes the partner for each point redeemed at the partner; both are accepted from 0 through 100000 inclusive. The agreement's effective window is the closed interval from `effective_start_date` through `effective_end_date`, and the end must fall strictly after the start, else `ERR_INVALID_WINDOW`. The create request also carries `settlement_lag_days`, `net_settlement_enabled` and `min_invoice_cents`; an agreement that leaves them unset takes 30 whole days of lag, netting disabled, and a minimum invoice of 5000 cents. `settlement_lag_days` is accepted from 0 through 365 inclusive and `min_invoice_cents` must not be negative.

`settlement_lag_days` does double duty. It is the number of whole days added to a period's `end_at` to obtain a statement's `due_date`, and it is also the mandatory buffer between two agreements that share a `partner_code`. Concretely: a new agreement conflicts with any existing non-`TERMINATED` agreement on the same programme carrying the same `partner_code` whenever the new agreement's `effective_start_date` falls on or before that prior agreement's `effective_end_date` advanced by the prior agreement's own `settlement_lag_days` whole days. Adjacency is therefore not sufficient — the new window must begin strictly after the prior window's settlement tail — and a conflict is rejected with `ERR_PARTNER_WINDOW_CONFLICT`. A new agreement is born with `status` `ACTIVE`, `deferred_below_minimum_cents` at 0 and `outstanding_settlement_cents` at 0.

A `LoyaltyAccountant` measures a **SettlementStatement** for exactly one pairing of agreement and period, naming `partner_agreement_id` and `period_id` and carrying `expected_partner_agreement_version` as §2.7 requires. The agreement must be `ACTIVE` — a `SUSPENDED` or `TERMINATED` agreement yields `ERR_AGREEMENT_NOT_ACTIVE` — the period must not be `HARD_CLOSED`, and the period and the agreement must belong to the same programme, else `ERR_PERIOD_PROGRAM_MISMATCH` or `ERR_AGREEMENT_PROGRAM_MISMATCH` as appropriate.

Measurement looks only at lots and events matching **both** the statement's `partner_agreement_id` and its `period_id`; anything with no partner agreement is never included. `partner_issued_points` is the sum of `points_issued` over the matching lots, with every `lifecycle_state` included — issuance is billable the moment it happens, and a later redemption, expiry or escheatment does not un-bill it. `partner_redeemed_points` is the sum of `points_requested` over the matching redemption events whose `state` is `ALLOCATED` or `FULFILLED`; events still merely `REQUESTED`, and events that were `REVERSED`, contribute nothing. From those two counts, `issuance_receivable_cents` is `partner_issued_points` multiplied by the agreement's `issuance_rate_millicents_per_point`, divided by 1000, rounded half up, and `redemption_payable_cents` is `partner_redeemed_points` multiplied by the agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up. Each leg is rounded independently.

The statement then picks up whatever the previous statement was too small to bill: `carried_forward_cents` is a snapshot of the agreement's `deferred_below_minimum_cents` read before this statement overwrites it, and it is 0 on an agreement's first statement. What happens next depends on `settlement_basis`, which is computed at creation from the agreement: `NET` when `net_settlement_enabled` is true, `GROSS` when it is false.

- Under `GROSS`, the billable candidate is `issuance_receivable_cents` plus `carried_forward_cents`. The redemption payable is still measured and reported on the statement, but it is **not** offset here — it settles on the partner's own invoice outside this ledger.
- Under `NET`, the billable candidate is `issuance_receivable_cents` less `redemption_payable_cents` plus `carried_forward_cents`. The payable is offset inside the statement, and the candidate may come out negative, in which case it necessarily falls below the minimum invoice and is deferred rather than billed.

The minimum-invoice threshold is applied to the candidate **after** the carry-forward has been added, never to the current period's legs alone — applying it earlier would strand the carry-forward forever. When the candidate is strictly less than the agreement's `min_invoice_cents`, `net_due_cents` is 0 and `deferred_below_minimum_cents` takes the whole candidate. Otherwise `net_due_cents` takes the candidate and `deferred_below_minimum_cents` is 0. Either way the statement's `deferred_below_minimum_cents` is copied onto the agreement's own `deferred_below_minimum_cents`, where the next statement will find it as its carry-forward; the value is signed, a positive figure meaning the partner still owes the programme and a negative figure meaning the programme still owes the partner. `due_date` is the period's `end_at` advanced by the agreement's `settlement_lag_days` whole days. `net_due_cents` is signed on the same convention as the carry-forward.

A new statement is born in `state` `DRAFT`, with `dispute_count` at 0 and `issued_at`, `paid_at`, `dispute_reason`, `resolution_note` and `write_off_reason` all null. Creating it drives any existing statement for the same agreement-and-period pair that is still `DRAFT` to `SUPERSEDED`, incrementing that statement's `version` by 1 — this legitimate supersession is exactly why the create is guarded by a version check rather than by a state precondition. Creation also increments the agreement's `version` by 1.

Issuing a statement is a `LoyaltyAccountant` action that moves it `DRAFT → ISSUED`, requires the owning agreement to be `ACTIVE`, sets `issued_at` to the clock reading, adds the statement's `net_due_cents` to the agreement's `outstanding_settlement_cents`, and increments both the agreement's and the statement's `version` by 1.

Once issued, the partner may push back. A `PartnerOperator` whose `X-User-ID` is the statement's `partner_agreement_id` — and no one else, on pain of `ERR_NOT_RESOURCE_OWNER` — moves the statement `ISSUED → DISPUTED` with a `dispute_reason`, provided its `dispute_count` is below 2. The dispute stores the reason, increments `dispute_count` by 1 and increments `version` by 1. A `LoyaltyAccountant` resolves the dispute, moving the statement `DISPUTED → ISSUED` with a `resolution_note`, which is stored alongside a refreshed `issued_at`, and incrementing `version` by 1. Resolution never re-measures `net_due_cents`; the bounded cycle `ISSUED → DISPUTED → ISSUED` may therefore run at most twice before `ERR_DISPUTE_LIMIT_EXCEEDED` closes it off.

Settlement finishes in a `Controller`'s hands, and both endings cascade into the lots. Payment moves the statement `ISSUED → PAID`, which is terminal: it sets `paid_at` to the clock reading, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, increments the agreement's `version` by 1 and the statement's `version` by 1, and drives every lot sharing the statement's `partner_agreement_id` and `period_id` whose `settlement_state` is `PENDING_SETTLEMENT` to `SETTLED`, walking those lots in `created_at` ascending order and incrementing each lot's `version` by 1. Write-off is available from `ISSUED → WRITTEN_OFF` and equally from `DISPUTED → WRITTEN_OFF`; both paths behave identically. A write-off stores the supplied `write_off_reason`, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, drives every matching `PENDING_SETTLEMENT` lot of the same agreement-and-period pair to `WRITTEN_OFF` in `created_at` ascending order with each lot's `version` incremented by 1, additionally drives the owning agreement `ACTIVE → SUSPENDED` — no new statement may be created while an agreement is suspended — and increments both the agreement's and the statement's `version` by 1.

Terminating an agreement is a `ProgramAdmin` action, permitted from `ACTIVE → TERMINATED` and from `SUSPENDED → TERMINATED`, and only when the agreement's `outstanding_settlement_cents` is exactly 0; a non-zero balance is rejected with `ERR_OUTSTANDING_SETTLEMENT`. Termination increments the agreement's `version` by 1, and `TERMINATED` is terminal.

### 3.6. Estimating Breakage: Measurement, Review and Approval

A **BreakageEstimate** is the actuarial artefact that tells the programme what share of its outstanding points it still expects to hand over. Only a `LoyaltyAccountant` prepares one, always under a named programme, and the request names the `period_id` of the period the estimate supports, may name a `cohort_id` to narrow the measurement to a single enrolment vintage, and supplies `memo_narrative`, `sensitivity_low_bp` and `sensitivity_high_bp`. The programme must be `ACTIVE`, the period must be `OPEN`, the period must belong to that programme (`ERR_PERIOD_PROGRAM_MISMATCH`), and any named cohort must belong to it too (`ERR_COHORT_PROGRAM_MISMATCH`). `memo_narrative` is the actuarial memorandum text of at most 2000 characters; the field must be present in the create request, but the empty string is accepted at this stage — the memorandum only becomes mandatory later, when the period it supports is hard-closed. `sensitivity_low_bp` and `sensitivity_high_bp` are both required and are **absolute** redemption-rate scenarios in basis points rather than deltas, each accepted from 200 through 9800 inclusive.

Measurement runs at creation and is frozen thereafter. The candidate set is built from the programme's cohorts that carry a non-zero weight, where a cohort's **weight** is the total `points_remaining` over the lots held by that cohort's members whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`. Lots that are `FULLY_REDEEMED`, `EXPIRED` or `ESCHEATED` contribute nothing — neither to a weight nor to any gross figure. Candidates are considered in order of `enrollment_start_date` ascending and then `created_at` ascending. If no candidate cohort carries any outstanding points, the estimate cannot be measured and the request is rejected with `ERR_NO_OUTSTANDING_POINTS`.

The measurement itself is a two-step weighted mean, and the order of the two steps is normative:

- **Per-cohort adjusted rate, clamped per cohort.** For each candidate cohort, add its `program_change_adjustment_bp` to its `observed_redemption_rate_bp`, then clamp the sum into the band from 200 through 9800 basis points inclusive — a sum below 200 becomes 200, a sum above 9800 becomes 9800.
- **Weight the already-clamped rates, then round once.** Multiply each cohort's clamped rate by that cohort's weight, add those products together, divide by the total of all the weights, and round half up once to a whole number of basis points. That is `estimated_redemption_rate_bp`.

The clamp belongs to the first step and is applied per cohort **before** weighting. Clamping the weighted result instead produces a different rate whenever any single cohort's raw adjusted rate falls outside the 200-to-9800 band, and that different rate is wrong.

From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`. `outstanding_points_at_estimate` is the total weight — that is, the total outstanding points over the lot set that was measured. `outstanding_gross_ssp_cents_at_estimate` is the sum, over that same lot set, of each lot's `remaining_gross_ssp_cents`, with each lot rounded first and the rounded amounts then added. The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment.

Three measurement variants exist, and `method_applied` records which one actually ran:

- `COHORT_WEIGHTED` runs when the programme's `breakage_method` is `COHORT_WEIGHTED` and the request omits `cohort_id`. It uses the full multi-cohort weighted formula above, including the case where exactly one cohort qualifies.
- `SINGLE_COHORT` runs whenever the request supplies `cohort_id`, regardless of the programme's `breakage_method`. The candidate set is restricted to that one cohort, so the total weight is that cohort's weight and the weighted mean collapses to that cohort's own clamped adjusted rate — its `observed_redemption_rate_bp` plus its `program_change_adjustment_bp`, clamped into 200 through 9800 — with no division and therefore no division rounding. The named cohort must itself carry a weight above zero, or `ERR_NO_OUTSTANDING_POINTS` is returned.
- `PROGRAM_HISTORICAL` runs when the programme's `breakage_method` is `PROGRAM_HISTORICAL` and the request omits `cohort_id`. Cohort weights and adjustments are ignored entirely and `estimated_redemption_rate_bp` takes the programme's `historical_redemption_rate_bp` verbatim. `outstanding_points_at_estimate` and `outstanding_gross_ssp_cents_at_estimate` are still measured over the same lot set, so `required_liability_cents` still varies with the outstanding balance, and `ERR_NO_OUTSTANDING_POINTS` still applies when nothing is outstanding.

Once the rate is known, the sensitivity band is checked: `sensitivity_low_bp` must be no greater than the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp` must be no less than it. A band that fails to straddle the measured rate is rejected with `ERR_SENSITIVITY_BAND_INVALID`. The estimate is then persisted in `state` `DRAFT`, with `prepared_by_user_id` set to the acting `X-User-ID`, `revision_count` at 0, `supersedes_estimate_id` null, `approved_by_user_id` null, `rejection_reason` null, and `submitted_at` and `approved_at` both null.

Audit support reads the frozen snapshot rather than live data. A `LoyaltyAccountant` or a `Controller` may ask one estimate for its sensitivity bands, and the answer is computed from the estimate's own `outstanding_gross_ssp_cents_at_estimate` — never from a fresh measurement — which is what makes the band reproducible long after the underlying lots have moved. The response reports that frozen gross as `outstanding_gross_ssp_cents`, echoes the three scenarios as `low_bp`, `base_bp` and `high_bp` (respectively `sensitivity_low_bp`, the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp`), and gives `low_required_liability_cents`, `base_required_liability_cents` and `high_required_liability_cents` as the frozen gross multiplied by each of those three rates in turn, divided by 10000, each rounded half up **independently** — deriving the high band by adding a rounded delta onto the rounded base drifts and is wrong. `band_range_cents` is the high band less the low band, and `memo_narrative` is echoed from the estimate. Because everything is drawn from the snapshot, the band is identical before and after the estimate is approved or superseded.

Review is a bounded loop. A `LoyaltyAccountant` submits a `DRAFT` estimate, moving it `DRAFT → SUBMITTED`, which requires the supporting period to be `OPEN`, sets `submitted_at` to the clock reading and increments `version` by 1. A `Controller` may push back, moving the estimate `SUBMITTED → REJECTED` with a `rejection_reason` that is stored on the estimate, incrementing `version` by 1. A rejected estimate may be resubmitted, `REJECTED → SUBMITTED`, provided the period is still `OPEN` and `revision_count` is below 2; that path increments `revision_count` by 1, refreshes `submitted_at` to the clock reading and increments `version` by 1, and a third attempt is rejected with `ERR_REVISION_LIMIT_EXCEEDED`. Crucially, `estimated_redemption_rate_bp` is **never** re-measured on resubmission — it stays frozen at the value computed when the estimate was created, however much the underlying balances have moved in the meantime.

Approval is a `Controller` action, moves the estimate `SUBMITTED → APPROVED`, and is the most consequential single request in the system. It requires the estimate to be `SUBMITTED`, its period to be `OPEN`, `expected_program_version` in the request body to equal the programme's current `version` (otherwise `ERR_STALE_PROGRAM_VERSION`, HTTP 412), and the acting `X-User-ID` to differ from the estimate's `prepared_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). On success it sets `approved_by_user_id` to the acting `X-User-ID` and `approved_at` to the clock reading, increments the estimate's `version` by 1, and then fires a three-link chain:

- **First link.** The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1. Every lot issued from this moment on will snapshot the new rate, and every subsequent fulfilment will re-measure at it.
- **Second link, caused by the first replacing the reigning rate.** The programme's other estimate whose `state` is `APPROVED` — there is at most one — moves `APPROVED → SUPERSEDED` with its `version` incremented by 1, and the newly approved estimate's `supersedes_estimate_id` is set to that retired estimate's `id`. When the programme had no approved estimate yet, `supersedes_estimate_id` stays null.
- **Third link, caused by the second retiring the old estimate.** The retired estimate's own accounting period, **if and only if** that period is `SOFT_CLOSED`, is force-reopened `SOFT_CLOSED → OPEN`, because its close no longer rests on a live approved estimate. That forced reopen resets the period's `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp` to 0, sets `soft_closed_at` to null, increments `reopen_count` by 1 and increments the period's `version` by 1. A period that is `HARD_CLOSED`, or already `OPEN`, is left entirely untouched. Unlike the manual reopen, this forced reopen is not gated on `reopen_count` being below 2 — but it does consume that budget, since the counter still increments.

`SUPERSEDED` is terminal for an estimate. A programme therefore has at most one live approved estimate at any instant, and the moment a new one is installed, any soft close resting on the old one is unwound.

### 3.7. Closing the Books: The Eight-Step Liability Rollforward

Closing a period is the moment the incremental movement accumulators are reconciled against a fresh actuarial measurement. The rollforward has **eight strictly ordered steps**; each consumes the results of the earlier ones, and permuting them changes the answer.

- **Step 1 — opening liability.** `opening_liability_cents` is taken from the `closing_liability_cents` of the programme's latest already-closed period: among the sibling periods of the same programme whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`, the one with the greatest `end_at`, and where two share the same `end_at`, the one created last. When the programme has no closed period at all, `opening_liability_cents` is 0.
- **Steps 2 to 5 — the movement accumulators.** `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents` and `expiry_released_cents` are **frozen as they stand**. They were maintained incrementally by issuance, allocation, fulfilment, reversal and expiry as those events happened, and the close does not recompute them from the underlying rows.
- **Step 6 — pre-catch-up liability.** `pre_catchup_liability_cents` is `opening_liability_cents` **plus** `issuance_deferred_cents`, **less** `redemption_recognized_cents`, **less** `remeasurement_delta_cents`, **less** `expiry_released_cents`. That sign order is normative: only the deferral of new issuance increases the liability, and every release — recognised redemption, the re-measurement delta and expiry — reduces it.
- **Step 7 — required liability from the approved rate.** `approved_estimate_rate_bp` is copied from the `estimated_redemption_rate_bp` of the `APPROVED` estimate belonging to this period. The outstanding gross standalone selling price is then measured **at close**, over the programme's lots — programme-wide, not period-scoped, because a lot issued in an earlier period still carries liability into this period's required balance — whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, summing each lot's `points_remaining` multiplied by its own `ssp_millicents_per_point_at_issue` divided by 1000 and rounded half up per lot. `required_liability_cents` is that at-close gross multiplied by `approved_estimate_rate_bp`, divided by 10000, rounded half up. The estimate's own frozen `outstanding_gross_ssp_cents_at_estimate` is **not** reused here; measuring at close is what makes the catch-up reflect every redemption and expiry that happened between approval and close.
- **Step 8 — catch-up, closing balance and recognised breakage.** `catch_up_adjustment_cents` is `required_liability_cents` less `pre_catchup_liability_cents`, and may be negative. `closing_liability_cents` is `pre_catchup_liability_cents` plus `catch_up_adjustment_cents`. `breakage_recognized_cents` is the negation of `catch_up_adjustment_cents` — negative when the liability must be topped up and positive when it is released.

Steps 6 and 8 are exact integer arithmetic; the only rounding in the whole rollforward happens inside Step 7. A period with no issuance, no redemption and no expiry still produces a non-zero `catch_up_adjustment_cents` whenever prior-period lots remain outstanding and the approved rate has moved since the last close.

A `Controller` soft-closes a period, driving it `OPEN → SOFT_CLOSED`. This requires the period to be `OPEN`, the logical clock to have reached or passed `end_at` (otherwise `ERR_PERIOD_NOT_ENDED`), an `APPROVED` estimate to exist for this period (otherwise `ERR_ESTIMATE_NOT_APPROVED`), and no `RedemptionEvent` of this period to still be in state `REQUESTED` (otherwise `ERR_UNALLOCATED_REDEMPTIONS`, since an unallocated request would leave revenue unmeasured). On success the eight steps run in the pinned order, `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp` are persisted, `soft_closed_at` is set to the clock reading, and `version` increments by 1.

A `Controller` may reopen a soft-closed period, `SOFT_CLOSED → OPEN`, provided `reopen_count` is below 2 (otherwise `ERR_REOPEN_LIMIT_EXCEEDED`). The reopen is a full compensation: `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp` all reset to 0, `soft_closed_at` becomes null, `reopen_count` increments by 1 and `version` increments by 1. Because the programme's `recognized_breakage_ytd_cents` only sums the periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`, dropping this period out of that set returns the programme-level figure to its exact pre-close value with zero drift. The movement accumulators are deliberately **not** reset — they belong to the events that produced them, not to the close.

A `Controller` hard-closes a soft-closed period, `SOFT_CLOSED → HARD_CLOSED`, which is terminal. Two preconditions apply: the `APPROVED` estimate for this period must carry a non-empty `memo_narrative` (otherwise `ERR_MEMO_NARRATIVE_REQUIRED`) — the memorandum that could be left empty at estimate creation must exist by the time the books are sealed — and every `SettlementStatement` of this period must be in `PAID`, `WRITTEN_OFF` or `SUPERSEDED` (otherwise `ERR_UNSETTLED_STATEMENTS`). `version` increments by 1, and thereafter no child of the period may be mutated at all.

Auditors do not have to close a period to see what closing would produce. A `LoyaltyAccountant` or `Controller` may ask an open period for its liability rollforward preview, which re-runs all eight steps against current data and **persists nothing** — no field is written, no `version` is bumped, and the period's `state` is unchanged. The preview reports `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `pre_catchup_liability_cents`, `outstanding_gross_ssp_cents` (the at-close gross the required balance was measured on), `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp`.

### 3.8. Expiry, Escheatment and Dormancy

Expiry is swept, not scheduled. A `LoyaltyAccountant` runs a sweep against one accounting period, which must be `OPEN` because the sweep books its releases and accruals into that period, and the sweep then examines the lots of that period's **whole programme** — not merely the lots booked to the swept period. Candidates are the programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` and whose `expires_at` is at or before the clock reading; the comparison is inclusive, so a lot whose `expires_at` is exactly the current clock reading is eligible while one an instant later is not. Lots already `EXPIRED` or `ESCHEATED` are never re-swept, and `settlement_state` is irrelevant to eligibility. Candidates are processed in `issued_at` ascending order, then `created_at` ascending.

For each candidate, the governing policy is the `StateExpiryRule` matching the owning member's programme and the member's `state_code`. Three conditions cause the lot to be **skipped silently** — never reported as an error: no rule exists for that state code, the rule's `expiry_permitted` is false, or the member's `dormancy_days` is below the rule's `min_dormancy_days`. A missing rule is treated exactly as `expiry_permitted` false.

Every eligible lot is measured **before** it is emptied, and that order is essential:

- `expired_gross_ssp_cents` is captured from the lot's current `remaining_gross_ssp_cents`, and the released deferral is captured from its current `remaining_deferred_cents`. Both are read while `points_remaining` still holds the surviving balance; reading them after the balance is zeroed yields 0 for both and silently books nothing.
- `points_remaining` is then set to 0 and `lifecycle_state` moves `OUTSTANDING → EXPIRED` or `PARTIALLY_REDEEMED → EXPIRED`.
- The captured released deferral is added to the **swept** period's `expiry_released_cents`, and the lot's `version` increments by 1.

Escheatment is a second link, caused by the expiry completing rather than by the sweep request. When the governing rule's `escheatment_required` is true, `escheated_cents` is `expired_gross_ssp_cents` multiplied by the rule's `escheat_rate_bp`, divided by 10000, rounded half up; `lifecycle_state` moves `EXPIRED → ESCHEATED`, which is terminal for the lifecycle dimension; the amount is added both to the swept period's `escheat_accrual_cents` and to the programme's `total_escheat_accrual_cents`; and a third link fires from that accrual — once the programme's `total_escheat_accrual_cents` reaches `escheat_disclosure_threshold_cents`, the boundary being inclusive, `escheat_disclosure_required` latches to true and is never cleared again, even if a later reopen reduces other figures. A rule with `escheat_rate_bp` of 10000 escheats the entire expired gross. When `escheatment_required` is false, `escheated_cents` stays 0 and the lot rests at `EXPIRED`.

Dormancy is a fan-out evaluated once per member touched by the sweep's expiry pass, in `created_at` ascending order. A member whose `status` is `ACTIVE`, whose `point_balance` is 0 after the pass, and whose `dormancy_days` is at least 730 — two years since `last_activity_at` — moves `ACTIVE → DORMANT` with `version` incremented by 1. Dormancy is not terminal: the next issuance to that member revives it.

Two version-counting details are load-bearing. The programme's `version` increments **once per sweep request**, not once per expired lot, however many lots the sweep touches — including when escheatment accrues against the programme several times. The swept period's `version` also increments by 1 for the request.

### 3.9. Programme Change Orders: Modelling Before Mutating

A programme's economics may only be changed through a modelled, approved and applied **ProgramChangeOrder**. A `ProgramAdmin` creates one against a `program_id` with a `change_type` of `EXPIRY_DAYS_CHANGE`, `SSP_CHANGE` or `TIER_MULTIPLIER_CHANGE`, and supplies exactly the one new-value field that matches: `new_point_expiry_days` (1 through 3650) for `EXPIRY_DAYS_CHANGE`, `new_ssp_millicents_per_point` (1 through 100000) for `SSP_CHANGE`, or `new_tier_multiplier_bp` for `TIER_MULTIPLIER_CHANGE`. The new-value field matching the declared `change_type` must be present and the other two must be omitted; a request that breaches that shape, or that carries a new value outside its declared range, is rejected as a malformed request with `ERR_INVALID_REQUEST`. A supplied `new_tier_multiplier_bp` must carry exactly the same four keys `BASE`, `SILVER`, `GOLD` and `PLATINUM` as the programme's own `tier_multiplier_bp`, each value an integer from 10000 through 50000, and a key set that differs is rejected with `ERR_TIER_MULTIPLIER_KEYS_INVALID`. The order also carries `behavior_elasticity_bp`, from -5000 through 5000, expressing how the change is expected to move redemption behaviour, and `effective_at`, which must be at or after the clock reading at the moment of creation.

Creation runs the liability projection and freezes it. `baseline_redemption_rate_bp` is 10000 basis points less the programme's `current_breakage_rate_bp`. `projected_redemption_rate_bp` is that baseline plus `behavior_elasticity_bp`, clamped into the band from 200 through 9800 inclusive, so a large elasticity saturates rather than escaping the band. Both gross figures are measured over the **same** lot set — the programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` — but at different prices: `baseline_outstanding_gross_ssp_cents` sums each lot's `points_remaining` multiplied by that lot's own `ssp_millicents_per_point_at_issue` divided by 1000, rounded half up per lot, while `projected_outstanding_gross_ssp_cents` reprices the identical lot set at `new_ssp_millicents_per_point` for an `SSP_CHANGE` and is otherwise identical to the baseline. `projected_liability_delta_cents` is then the projected gross multiplied by the projected rate divided by 10000 and rounded half up, **less** the baseline gross multiplied by the baseline rate divided by 10000 and rounded half up: each leg is rounded independently and only then subtracted, since rounding the difference of the two unrounded products gives a different figure. The delta may be negative. For `EXPIRY_DAYS_CHANGE` and `TIER_MULTIPLIER_CHANGE` the two grosses are equal, so the delta is driven purely by `behavior_elasticity_bp`. The order is born in `state` `MODELED`, the programme is untouched, and the projection is **never** re-measured when the order is later approved or applied.

A `Controller` approves an order, `MODELED → APPROVED`, which requires the programme's `status` to be `ACTIVE`. Approval is exclusive within its change type: every **other** order of the same programme with the same `change_type` and `state` `MODELED` moves `MODELED → CANCELLED` with `cancelled_by_order_id` set to the approved order's `id`, processed in `created_at` ascending order and each incrementing its own `version` by 1. Competing orders of a *different* change type are untouched. The approved order's `version` increments by 1.

A `Controller` applies an approved order, `APPROVED → EFFECTIVE`, which is terminal, and only once the clock has reached or passed `effective_at` — an earlier attempt is rejected with `ERR_CHANGE_NOT_YET_EFFECTIVE`. Application fires a three-link chain:

- **First link.** The order's new value is written onto the programme — `new_point_expiry_days` onto `point_expiry_days`, `new_ssp_millicents_per_point` onto `ssp_millicents_per_point`, or `new_tier_multiplier_bp` onto `tier_multiplier_bp` — and the programme's `version` increments by 1.
- **Second link, caused by the first changing the expiry horizon, and only for `EXPIRY_DAYS_CHANGE`.** Every lot of the programme whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` has its `expires_at` recomputed as its own `issued_at` plus the **new** `point_expiry_days` whole days, processed in `created_at` ascending order, each lot's `version` incrementing by 1. Lots that are `FULLY_REDEEMED`, `EXPIRED` or `ESCHEATED` are not re-dated. For the other two change types this link does nothing to `expires_at`.
- **Third link.** Every cohort of the programme has its `program_change_adjustment_bp` increased by the order's `behavior_elasticity_bp`, with the result clamped into the range -5000 through 5000, processed in `enrollment_start_date` ascending then `created_at` ascending order, each cohort's `version` incrementing by 1. This link fires for **all three** change types, so a tier or SSP change still shifts the behavioural adjustment that future breakage estimates will weight.

`applied_at` is set to the clock reading and the order's `version` increments by 1. Already-issued lots keep their `ssp_millicents_per_point_at_issue`, `tier_multiplier_bp_at_issue` and `breakage_rate_bp_at_issue` snapshots forever: a change order redirects the future, never the measurement of the past. Only `expires_at`, which is a policy horizon rather than a measurement, is retroactively rewritten, and only for outstanding lots.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the created resource in `data`. Every other endpoint — reads, transition actions and the clock control — returns HTTP 200, and transition actions return the updated resource. The computed reads return the field sets described in §3.6 and §3.7 rather than a stored entity. Error responses use the statuses catalogued in §5. Every collection is top-level; there is no shared path prefix. `RedemptionAllocation` is immutable and has no collection of its own — it is reached only through the two sub-resource reads.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Sets the server's logical UTC clock, which every timestamp comparison reads. Mutates no entity and bumps no version. | ProgramAdmin, LoyaltyAccountant, Controller |
| POST | `/programs` | Creates a LoyaltyProgram in status `DRAFT`. | ProgramAdmin |
| GET | `/programs` | Lists LoyaltyPrograms. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/programs/{id}` | Reads one LoyaltyProgram, including the derived `total_deferred_revenue_cents` and `recognized_breakage_ytd_cents`. | ProgramAdmin, LoyaltyAccountant, Controller |
| POST | `/programs/{id}/activate` | Drives `DRAFT → ACTIVE` (first activation, which seeds the breakage rate) or `SUSPENDED → ACTIVE` (reactivation, which does not). | ProgramAdmin |
| POST | `/programs/{id}/suspend` | Drives `ACTIVE → SUSPENDED`, blocking issuance and redemption. | ProgramAdmin |
| POST | `/programs/{id}/close` | Drives `ACTIVE` or `SUSPENDED → CLOSED`; every period must be hard-closed. | ProgramAdmin |
| POST | `/state-expiry-rules` | Declares the expiry and escheatment policy for one state under one programme. | ProgramAdmin |
| GET | `/state-expiry-rules` | Lists StateExpiryRules; filterable by programme, state code and expiry permission. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/state-expiry-rules/{id}` | Reads one StateExpiryRule. | ProgramAdmin, LoyaltyAccountant, Controller |
| POST | `/cohorts` | Creates an enrolment Cohort carrying the historical redemption pattern used by breakage measurement. | ProgramAdmin, LoyaltyAccountant |
| GET | `/cohorts` | Lists Cohorts; filterable by programme and cohort code. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/cohorts/{id}` | Reads one Cohort, including `program_change_adjustment_bp` as mutated by applied change orders. | ProgramAdmin, LoyaltyAccountant, Controller |
| POST | `/members` | Enrols a Member into a Cohort of a programme, in status `ACTIVE`. | ProgramAdmin, LoyaltyAccountant |
| GET | `/members` | Lists Members; filterable by programme, cohort, status, state code and tier. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/members/{id}` | Reads one Member, including the derived `dormancy_days`, `point_balance` and `outstanding_gross_ssp_cents`. A Member may read only its own record. | ProgramAdmin, LoyaltyAccountant, Controller, Member |
| POST | `/accounting-periods` | Opens an AccountingPeriod over the half-open window from `start_at` up to but excluding `end_at`. | Controller |
| GET | `/accounting-periods` | Lists AccountingPeriods; filterable by programme, state and period code. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/accounting-periods/{id}` | Reads one AccountingPeriod with all eleven persisted rollforward figures. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/accounting-periods/{id}/liability-rollforward` | Computed read: re-runs the eight rollforward steps against current data without persisting anything, so an auditor can preview a close. | LoyaltyAccountant, Controller |
| POST | `/accounting-periods/{id}/soft-close` | Drives `OPEN → SOFT_CLOSED`, running and persisting the rollforward. | Controller |
| POST | `/accounting-periods/{id}/reopen` | Drives `SOFT_CLOSED → OPEN`, fully compensating the soft close. At most two reopens. | Controller |
| POST | `/accounting-periods/{id}/hard-close` | Drives `SOFT_CLOSED → HARD_CLOSED` (terminal); requires the memorandum on file and every statement settled. | Controller |
| POST | `/accounting-periods/{id}/expiry-sweep` | Sweeps the whole programme for expired lots, booking expiry releases and escheat accruals into this period. | LoyaltyAccountant |
| POST | `/partner-agreements` | Registers a partner agreement over the closed window from `effective_start_date` through `effective_end_date`, in status `ACTIVE`. | ProgramAdmin |
| GET | `/partner-agreements` | Lists PartnerAgreements; filterable by programme, partner code, status and relationship type. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/partner-agreements/{id}` | Reads one PartnerAgreement. A PartnerOperator may read only the agreement it acts as. | ProgramAdmin, LoyaltyAccountant, Controller, PartnerOperator |
| POST | `/partner-agreements/{id}/terminate` | Drives `ACTIVE` or `SUSPENDED → TERMINATED` (terminal); requires a zero outstanding settlement balance. | ProgramAdmin |
| POST | `/point-lots` | Issues a PointLot, running the issuance measurement and its snapshots. | LoyaltyAccountant |
| GET | `/point-lots` | Lists PointLots; filterable by member, period, partner agreement and either state dimension. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/point-lots/{id}` | Reads one PointLot, including the derived `remaining_gross_ssp_cents` and `remaining_deferred_cents`. A Member may read only its own lots. | ProgramAdmin, LoyaltyAccountant, Controller, Member |
| GET | `/point-lots/{id}/allocations` | Sub-resource read: the append-only allocation ledger rows that consumed or restored this lot. | ProgramAdmin, LoyaltyAccountant, Controller |
| POST | `/redemption-events` | Requests a redemption of `points_requested` points for a member, in state `REQUESTED`. | LoyaltyAccountant, Member |
| GET | `/redemption-events` | Lists RedemptionEvents; filterable by member, period, partner agreement, state and redemption type. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/redemption-events/{id}` | Reads one RedemptionEvent. A Member may read only its own events. | ProgramAdmin, LoyaltyAccountant, Controller, Member |
| GET | `/redemption-events/{id}/allocations` | Sub-resource read: this event's append-only allocation ledger rows, `ALLOCATION` rows positive and `REVERSAL` rows negated. | ProgramAdmin, LoyaltyAccountant, Controller |
| POST | `/redemption-events/{id}/allocate` | Drives `REQUESTED → ALLOCATED`, consuming lots oldest-first and releasing revenue provisionally. | LoyaltyAccountant |
| POST | `/redemption-events/{id}/fulfill` | Drives `ALLOCATED → FULFILLED`, re-measuring at the current rate and booking the re-measurement delta. | LoyaltyAccountant |
| POST | `/redemption-events/{id}/reverse` | Drives `ALLOCATED` or `FULFILLED → REVERSED` (terminal), compensating every ledger effect with negated rows. | LoyaltyAccountant |
| POST | `/programs/{id}/breakage-estimates` | Creates a `DRAFT` BreakageEstimate for one period of the programme, freezing the measurement snapshot. | LoyaltyAccountant |
| GET | `/breakage-estimates` | Lists BreakageEstimates; filterable by programme, period, cohort, superseded estimate, state and method. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/breakage-estimates/{id}` | Reads one BreakageEstimate, including the frozen snapshot and the memorandum. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/breakage-estimates/{id}/sensitivity` | Computed read for audit support: the low, base and high required-liability band over the frozen snapshot. | LoyaltyAccountant, Controller |
| POST | `/breakage-estimates/{id}/submit` | Drives `DRAFT → SUBMITTED` or `REJECTED → SUBMITTED` (at most two revisions). The measured rate is never recomputed. | LoyaltyAccountant |
| POST | `/breakage-estimates/{id}/reject` | Drives `SUBMITTED → REJECTED` with a reason. | Controller |
| POST | `/breakage-estimates/{id}/approve` | Drives `SUBMITTED → APPROVED` under programme optimistic concurrency and segregation of duties, installing the new rate. | Controller |
| POST | `/settlement-statements` | Creates a `DRAFT` SettlementStatement for one agreement-and-period pair under agreement optimistic concurrency. | LoyaltyAccountant |
| GET | `/settlement-statements` | Lists SettlementStatements; filterable by agreement, period, state and settlement basis. A PartnerOperator sees only its own agreement's statements. | ProgramAdmin, LoyaltyAccountant, Controller, PartnerOperator |
| GET | `/settlement-statements/{id}` | Reads one SettlementStatement. A PartnerOperator may read only its own agreement's statements. | ProgramAdmin, LoyaltyAccountant, Controller, PartnerOperator |
| POST | `/settlement-statements/{id}/issue` | Drives `DRAFT → ISSUED`, booking the net due onto the agreement's outstanding balance. | LoyaltyAccountant |
| POST | `/settlement-statements/{id}/dispute` | Drives `ISSUED → DISPUTED`; only the operator acting as the statement's own agreement may dispute, at most twice. | PartnerOperator |
| POST | `/settlement-statements/{id}/resolve` | Drives `DISPUTED → ISSUED` with a resolution note; the net due is never re-measured. | LoyaltyAccountant |
| POST | `/settlement-statements/{id}/pay` | Drives `ISSUED → PAID` (terminal), clearing the balance and settling every partner lot of the pair. | Controller |
| POST | `/settlement-statements/{id}/write-off` | Drives `ISSUED` or `DISPUTED → WRITTEN_OFF`, writing off the partner lots and suspending the agreement. | Controller |
| POST | `/program-change-orders` | Models a proposed programme change in state `MODELED` with its liability projection; the programme is untouched. | ProgramAdmin |
| GET | `/program-change-orders` | Lists ProgramChangeOrders; filterable by programme, change type, state and cancelling order. | ProgramAdmin, LoyaltyAccountant, Controller |
| GET | `/program-change-orders/{id}` | Reads one ProgramChangeOrder, including the frozen projection. | ProgramAdmin, LoyaltyAccountant, Controller |
| POST | `/program-change-orders/{id}/approve` | Drives `MODELED → APPROVED` and cancels every competing modelled order of the same programme and change type. | Controller |
| POST | `/program-change-orders/{id}/apply` | Drives `APPROVED → EFFECTIVE` (terminal), writing the change onto the programme and cascading to lots and cohorts. | Controller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_STATE_EXPIRY_RULE_NOT_FOUND` | 404 |
| `ERR_COHORT_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PERIOD_NOT_FOUND` | 404 |
| `ERR_PARTNER_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_POINT_LOT_NOT_FOUND` | 404 |
| `ERR_REDEMPTION_EVENT_NOT_FOUND` | 404 |
| `ERR_BREAKAGE_ESTIMATE_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_STATEMENT_NOT_FOUND` | 404 |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_PERIOD_NOT_OPEN` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_PERIOD_HARD_CLOSED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_MEMO_NARRATIVE_REQUIRED` | 409 |
| `ERR_ESTIMATE_NOT_APPROVED` | 409 |
| `ERR_UNALLOCATED_REDEMPTIONS` | 409 |
| `ERR_INVALID_WINDOW` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_PARTNER_WINDOW_CONFLICT` | 409 |
| `ERR_PERIOD_NOT_ENDED` | 409 |
| `ERR_CHANGE_NOT_YET_EFFECTIVE` | 409 |
| `ERR_PERIOD_PROGRAM_MISMATCH` | 409 |
| `ERR_COHORT_PROGRAM_MISMATCH` | 409 |
| `ERR_AGREEMENT_PROGRAM_MISMATCH` | 409 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_TIER_MULTIPLIER_KEYS_INVALID` | 409 |
| `ERR_UNSETTLED_STATEMENTS` | 409 |
| `ERR_REVISION_LIMIT_EXCEEDED` | 409 |
| `ERR_REOPEN_LIMIT_EXCEEDED` | 409 |
| `ERR_DISPUTE_LIMIT_EXCEEDED` | 409 |
| `ERR_SENSITIVITY_BAND_INVALID` | 409 |
| `ERR_PROMO_MULTIPLIER_ABOVE_CAP` | 409 |
| `ERR_OUTSTANDING_SETTLEMENT` | 409 |
| `ERR_PERIODS_NOT_CLOSED` | 409 |
| `ERR_ISSUANCE_CAP_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_POINT_BALANCE` | 409 |
| `ERR_NO_OUTSTANDING_POINTS` | 409 |
| `ERR_PROGRAM_CONFIG_INCOMPLETE` | 409 |
