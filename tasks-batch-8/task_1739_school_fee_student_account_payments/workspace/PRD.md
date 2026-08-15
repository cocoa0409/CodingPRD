# School Fee & Student Account Payments API — Product Requirements Document

## 1. Introduction

The school bookkeeper's office sits at the intersection of academics and money: every course and activity carries a fee, families purchase optional items such as yearbooks and parking passes, eligible students receive fee waivers, and withdrawals or cancelled activities generate refunds. This document specifies an API that operates that entire landscape as one coherent system. It governs fee assessment driven by course and activity enrollment, optional purchases, online payment and family balances, waiver eligibility with automatic application, refund policy on withdrawal or activity cancellation, negative-balance and graduation-hold policy, department revenue distribution with reconciliation, payment plans for large balances, and the collections pipeline from aging through write-off to year close.

Three engineering commitments shape everything that follows. First, all money is integer cents and every rounding decision is pinned — the order in which truncation, caps, and remainders are applied is part of the contract, not an implementation detail. Second, time is a logical clock under the operator's control, so scheduled transitions — an offering entering session, an installment coming due, a collections case aging into the next bucket — are deterministic and reproducible. Third, sensitive writes are guarded: optimistic concurrency protects account- and year-level mutations whose preconditions depend on the client's last-observed state, and segregation-of-duties rules prevent the same operator from both requesting and approving a waiver, and prevent a write-off from being executed by the person who recorded the account's most recent payment.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled as follows: `Bookkeeper`, `FamilyMember`, and `Superintendent`. A request whose headers are missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); a request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The `Bookkeeper` is the school bookkeeper and operates the year configuration, assessments, refunds, payment plans, collections, and reconciliation. The `FamilyMember` is a parent or guardian acting on a student account: they submit waiver applications, initiate and settle payments, and purchase optional items. The `Superintendent` is the district superintendent, who co-approves large write-offs and is otherwise read-only. All three roles may use every read endpoint.

For all three roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `Bookkeeper`, the server may record the identifier where a scaffold transition writes it — for example as `reviewed_by_user_id` on a waiver application at decision time — but it never compares it to any entity's `id`. When `X-User-Role` is `FamilyMember`, the identifier is likewise opaque; it is recorded as `submitted_by_user_id` on each waiver application the family member submits, and the system remembers which identifier recorded each settled payment, but no ownership check ever compares `X-User-ID` against an entity `id`. When `X-User-Role` is `Superintendent`, the identifier is again opaque; it is recorded through the write-off co-approval action and never compared to any entity's `id`. Segregation-of-duties rules compare these recorded operator identifiers to one another — never to entity identifiers.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Transitions

The system never reads the wall clock. All time-dependent behavior — enrollment timestamps, refund proration windows, installment due dates, collections aging, posture checks — is governed by a single server-side **logical clock**. Before any operator call to set it, the logical clock is exactly 2026-08-01T00:00:00Z.

A `Bookkeeper` may advance the logical clock through an admin-only test-driving capability that accepts a to_iso8601 instant and responds with now_iso8601, the clock's new value. Clock-driven transitions are lazy: setting the clock does not itself mutate anything, but the new time is observed on the next read of an affected resource or on the next operations run. Two scheduled transitions ride on this mechanism. A `SCHEDULED` offering moves to `IN_SESSION` once the logical clock date reaches the offering's `start_date`, observed when the offering is read or when an operations run executes; the transition increments the offering's `version` by 1. A `SCHEDULED` installment moves to `DUE` once the logical clock reaches its `due_date`, observed on an operations run or an account read. The aging sweep (§3.8) runs only as part of an operations run.

### 2.5. Common Resource Properties and Version Semantics

Every primary resource carries a standard set of system-managed fields:

- id (string): a server-minted UUID with no type prefix.
- created_at (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- updated_at (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- version (integer): a system-managed integer that increments by 1 with every modification to the resource. Recomputation of derived fields — account aggregates, posture, department counters — is a mutation: it refreshes updated_at and increments version.

Two record types are immutable ledger rows and break this pattern: a PaymentAllocation row and a LedgerEntry row each carry only id and created_at. Both updated_at and version are absent on these two resources, because neither is ever modified after being written.

### 2.6. Money, Integer Cents, and Pinned Rounding Order

All monetary values are integer cents; there are no decimal money values anywhere in the system. Wherever a computation could produce a fractional cent, the rounding rule is specified at the point of use, and the order of operations is pinned:

- **Waiver stacking rounds down per program before caps.** Each program's tentative waiver on an assessment is the unpaid remainder times the program's basis-point rate divided by ten thousand, rounded down to a whole cent; only then is the result capped. Applying the cap first and truncating second is a different number and is wrong.
- **The payment waterfall splits proportionally with round-half-up.** When a stage-1 installment payment is spread across a plan's covered assessments, each per-assessment share is rounded half-up to a whole cent, and any residual cent of over- or under-allocation is assigned to the covered assessment with the earliest created_at.
- **Installment schedules divide by floor and push the remainder to the last installment.** The per-installment base is the covered total divided by the installment count, rounded down to a whole cent; the shortfall left by that floor division is added in full to the final installment, never the first.
- **Refund proration rounds down.** The partial-tier refund is the collected amount times the year's partial-refund basis-point rate divided by ten thousand, rounded down to a whole cent.
- **Aging is measured in whole days, rounded down**, with bucket boundaries that include the lower edge and exclude the upper edge (§3.8).
- **The graduation-hold threshold is strict**: the amount owed must be strictly greater than the threshold; an exact tie does not trigger the hold.

### 2.7. Calendar Semantics: Half-Open Offering Windows, Closed Year Ranges

Two date-overlap rules coexist, and they differ deliberately.

Offering schedules use **half-open intervals**. An offering occupies the window from its `start_date` up to but not including its `end_date`. Two offerings whose windows merely touch — one offering's `start_date` equal to another's `end_date` — do not conflict, and a student may be actively enrolled in both.

School-year ranges use **closed intervals**. A new school year's range from `start_date` through `end_date`, both endpoints included, must not intersect the range of any existing year that is not CLOSED. A shared endpoint date — the new year's start_date equal to an existing year's end_date — does collide, and the create is rejected with `ERR_YEAR_OVERLAP` (HTTP 409).

### 2.8. Hierarchy, Nested Retrieval, and Recomputed Aggregates

Resources nest: a school year owns departments, fee catalog items, optional purchase items, offerings, waiver programs, student accounts, and reconciliation runs; an account owns enrollments, fee assessments, purchases, waiver applications, payments, payment plans, refunds, ledger entries, and collections cases; a payment owns allocation rows; a plan owns installments.

For any request whose path contains multiple identifiers, existence is validated strictly left-to-right — the school year first, then the account, then the leaf resource. The first identifier that does not resolve to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404), and later identifiers are not examined. This applies to every path parameter, including {id}, {departmentId}, {itemId}, {offeringId}, {enrollmentId}, {assessmentId}, {purchaseId}, {programId}, {applicationId}, {paymentId}, {planId}, {refundId}, and {caseId}. Separately, identifiers referenced in a request body — offering_id, fee_item_id, department_id, waiver_program_id, item_id, student_id — must exist and belong to the same school-year scope as the resource being written; a body reference that fails this check is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404).

Derived state is recomputed eagerly. Whenever an event changes an account's underlying rows — an assessment created or voided, a waiver applied or revoked, a payment settled, a refund executed, a write-off, an aging sweep — the account's aggregates (assessed_cents, waived_cents, paid_cents, balance_cents, family_balance_cents) and its posture are recomputed immediately, last_posture_check_at is refreshed to the logical clock's current instant, and the account's updated_at and version advance per §2.5. The same recompute propagates upward: parent resources transition automatically when their children's states satisfy or violate the parent's criteria, with each such mutation refreshing the parent's updated_at and incrementing its version.

Every foreign-key relationship is also traversable in reverse through nested list reads — the accounts of a student, the offerings of a department, the assessments spawned by an enrollment, the allocation rows of a payment or of an assessment, the installments of a plan, the refunds sourced from an assessment or a purchase, and the ledger entries of a department, a payment, or a reconciliation run. Flat alias reads also exist for every entity, fetching one resource by its identifier without naming its ancestors.

### 2.9. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control. Each requires a non-optional version field carrying the client's last-observed `version` of the parent entity; if that value does not equal the parent entity's current `version` at the moment the write executes, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no mutation occurs.

- **Creating a payment plan** (`POST /student-accounts/{id}/payment-plans`) requires expected_account_version, matched against the owning student account's current version. The canonical stale case: a waiver approval or a payment settlement has recomputed the account's outstanding set since the client read it, so a plan built on the client's old view would cover the wrong amount.
- **Approving a waiver application** (`POST /student-accounts/{id}/waiver-applications/{applicationId}/approve`) requires expected_account_version, matched against the owning account's current version — the stacking base may have changed under the reviewer.
- **Closing a school year** (`POST /school-years/{id}/close`) requires expected_year_version, matched against the year's current version — a new collections case or payment plan may have appeared since the closer verified the close preconditions.

No other endpoint takes a version field. Reads never perform a version check.

### 2.10. The Validation Ladder and Error Precedence

Every request is checked against an ordered ladder of validations. Checks run in ascending priority order, and the first failing check determines the error returned — an earlier failure masks later ones. The ladder is:

1. **User context.** X-User-ID and X-User-Role must be present and well-formed — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role permission.** The role must be permitted for the endpoint — otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to all endpoints.
3. **Path existence.** Path identifiers must exist, validated left-to-right — otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to every endpoint with path identifiers.
4. **Body references.** Body-referenced identifiers must exist and belong to the same school-year scope — otherwise `ERR_REFERENCED_NOT_FOUND` (HTTP 404). Applies to endpoints with foreign-key body fields.
5. **Year open.** The school year must be OPEN for any enrollment, assessment, purchase, payment, or plan write under it — otherwise `ERR_YEAR_NOT_OPEN` (HTTP 409). Applies to write endpoints nested under a year and to account-scoped writes.
6. **From-state.** The target resource must be in the from-state its state machine requires — otherwise `ERR_INVALID_STATE` (HTTP 409). Applies to all state-transition endpoints.
7. **Request shape.** Required fields must be present, enums valid, and integers in range — amount_cents greater than zero, a school year's end_date strictly after its start_date, refund_partial_days strictly greater than refund_full_days, basis-point percentages within zero to ten thousand, capacity at least 1 — otherwise `ERR_INVALID_REQUEST` (HTTP 400). Applies to all write endpoints.
8. **Enrollment uniqueness.** No second ACTIVE enrollment may exist for the same account and offering — otherwise `ERR_DUPLICATE_ENROLLMENT` (HTTP 409). Applies to enrollment creation.
9. **Offering capacity.** The count of ACTIVE enrollments on the offering must be below its capacity — otherwise `ERR_OFFERING_FULL` (HTTP 409). Applies to enrollment creation.
10. **Enrollment window.** The offering must be SCHEDULED — otherwise `ERR_ENROLLMENT_WINDOW_CLOSED` (HTTP 409). Applies to enrollment creation.
11. **Schedule conflict.** The target offering's half-open window must not intersect the half-open window of any other offering with an ACTIVE enrollment on the same account; a shared boundary date does not collide — otherwise `ERR_SCHEDULE_CONFLICT` (HTTP 409). Applies to enrollment creation.
12. **Year overlap.** A new year's closed date range must not intersect any existing non-CLOSED year's range, and a shared endpoint date does collide — otherwise `ERR_YEAR_OVERLAP` (HTTP 409). Applies to school-year creation.
13. **Waiver review segregation.** The reviewer's X-User-ID must differ from the application's submitted_by_user_id — otherwise `ERR_WAIVER_SELF_APPROVAL` (HTTP 403). Applies to waiver approval, denial, and revocation.
14. **Waiver eligibility.** The program must be ACTIVE and the student's grade within the program's inclusive eligibility band — otherwise `ERR_WAIVER_INELIGIBLE` (HTTP 422). Applies to waiver approval.
15. **Payment idempotency.** The idempotency_key must be unique per account among payments that are not FAILED — otherwise `ERR_DUPLICATE_PAYMENT` (HTTP 409). Applies to payment initiation.
16. **Overpayment policy.** Under the REJECT policy, the settle amount must not exceed the account's allocatable capacity — otherwise `ERR_OVERPAYMENT_REJECTED` (HTTP 402). Applies to payment settlement.
17. **Payment plan terms.** The covered outstanding must be at least the year's payment_plan_min_cents, the installment count must lie between 2 and the year's payment_plan_max_installments inclusive, and there must be outstanding to cover — otherwise `ERR_PLAN_TERMS_VIOLATION` (HTTP 422). Applies to payment plan creation.
18. **Purchase inventory.** The item's sold_count must be below its inventory_cap — otherwise `ERR_ITEM_SOLD_OUT` (HTTP 409). Applies to purchase creation.
19. **Graduation gate.** No account of the student may hold posture GRADUATION_HOLD or COLLECTIONS — otherwise `ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION` (HTTP 409). Applies to graduation.
20. **Write-off aging.** The case's aging_bucket must be BUCKET_3 — otherwise `ERR_CASE_NOT_AGED` (HTTP 409). Applies to write-off execution.
21. **Write-off governance.** A write-off amount above the year's writeoff_max_cents requires the case's approved_writeoff_cents to cover the requested amount — otherwise `ERR_WRITEOFF_NEEDS_APPROVAL` (HTTP 403). Applies to write-off execution.
22. **Write-off segregation.** The write-off actor's X-User-ID must differ from the identifier that recorded the most recent SUCCEEDED payment on the account, when one exists — otherwise `ERR_WRITEOFF_SOD` (HTTP 403). Applies to write-off execution.
23. **Optimistic concurrency.** On concurrency-guarded endpoints, the expected_account_version or expected_year_version must equal the parent's current version — otherwise `ERR_STALE_VERSION` (HTTP 412). This check runs last, after every other validation has passed.

So, for example, enrollment creation evaluates its four business checks in the order uniqueness, then capacity, then window, then schedule conflict; waiver approval evaluates the segregation check (rung 13) before the eligibility check (rung 14); and write-off execution evaluates aging, then governance, then segregation.

### 2.11. The Department Revenue Ledger

Every cent that moves for a reason is recorded in a department-attributed ledger. A LedgerEntry carries the student_account_id giving account context, the credited or debited department_id, an entry_type, a signed amount_cents, the source_payment_id of the payment whose allocation produced a distribution (null on write-off rows), and a reconciliation_run_id that stays null until a reconciliation run stamps it. The entry_type is one of DISTRIBUTION_CREDIT, DISTRIBUTION_REVERSAL, WRITE_OFF_DEBIT, or WRITE_OFF_REVERSAL. Distribution credits are positive; distribution reversals are negative.

Two parallel ledgers exist side by side and never mix. The **fee ledger** — assessments, waivers, payments, fee refunds, payment plans, collections, write-offs — is what feeds an account's assessed_cents, waived_cents, paid_cents, and balance_cents. The **purchase ledger** — optional purchases and their refunds — writes its own distribution rows and drives sold_count, but purchases are not fee assessments and never enter assessed_cents, paid_cents, or balance_cents; a purchase refund writes its reversal and decrements sold_count without touching account balance math.

A department's distributed_cents is the sum of its DISTRIBUTION_CREDIT entries plus the sum of its DISTRIBUTION_REVERSAL entries (reversals being negative). Its reconciled_cents is the portion of distributions acknowledged by reconciliation runs and advances only when a reconciliation run executes; unreconciled_cents is distributed_cents minus reconciled_cents. The year-level invariant that reconciliation verifies — the sum of all departments' distributed_cents equals gross allocations on succeeded payments, plus completed and refunded purchase amounts, minus executed refunds, minus written-off cents — is stated fully in §3.8.

## 3. Business Logic & Workflows

### 3.1. Configuring the School Year: Terms, Departments, and Catalogs

Everything begins with the **school year**. A `Bookkeeper` creates it with a display label such as "2026-27", a start_date and an end_date (the end must be strictly after the start), and the policy knobs that govern every financial rule for the year: refund_full_days, the number of days from an offering's start during which a withdrawal earns a full refund, inclusive at the boundary; refund_partial_days, the inclusive outer edge of the partial-refund window, which must be strictly greater than refund_full_days; partial_refund_pct_bp, the partial-refund percentage in basis points from 0 to 10000; payment_plan_min_cents, the minimum total assessed balance required to open a payment plan; payment_plan_max_installments, the maximum installments a plan may spread over, at least 2; writeoff_max_cents, the largest single write-off a `Bookkeeper` may execute without `Superintendent` co-approval; aging_interval_days, the number of days between collections aging buckets; and graduation_hold_threshold_cents, the amount owed beyond which a graduation hold engages. Creating the year fails with `ERR_YEAR_OVERLAP` (HTTP 409) when its closed date range intersects any existing non-`CLOSED` year's range, including the shared-endpoint case described in §2.7. A new year is born `DRAFT`.

While the year is `DRAFT`, the `Bookkeeper` builds its configuration. **Departments** are created with a short code unique within the school year, such as "SCI" or "ATH", and a display name; each department's distributed_cents, reconciled_cents, and unreconciled_cents start at zero and evolve per §2.11 and §3.8. **Fee catalog items** define the price list: a name such as "AP Lab Fee", an amount_cents greater than zero, a department_id naming the default revenue department, and two booleans — waiverable, whether waivers may apply, and refundable, whether withdrawals and cancellations generate refunds — each defaulting to true when omitted. **Optional purchase items** carry a name such as "Yearbook" or "Parking Pass", an amount_cents price greater than zero, a department_id, a refundable flag defaulting to true, and an inventory_cap of at least 1 unit sellable per school year; the item's sold_count starts at 0. **Offerings** and **waiver programs** are configured here too, detailed in §3.3 and §3.4. The department list, fee-item list, and purchase-item list reads each accept a department_id filter alongside the standard pagination parameters; the fee-item list is the one place waiverable and refundable defaults are visible alongside amount_cents.

Opening the year is a deliberate act. A `Bookkeeper` may move the year `DRAFT` → `OPEN` only when at least one department exists for it — otherwise the attempt is rejected with `ERR_YEAR_NOT_CONFIGURABLE` (HTTP 409) — and when `end_date` is strictly after `start_date`. Opening sets `status` to `OPEN` and increments the year's version by 1. Only an `OPEN` year accepts the operational writes: enrollments, assessments, purchases, payments, and plans under a `DRAFT` or `CLOSED` year are rejected with `ERR_YEAR_NOT_OPEN` (HTTP 409).

Closing the year is the mirror act and is concurrency-guarded per §2.9: the close request must carry expected_year_version equal to the year's current version, else `ERR_STALE_VERSION` (HTTP 412). A year may close `OPEN` → `CLOSED` only when every collections case under the year's accounts is terminal — `RESOLVED` or `WRITTEN_OFF` — otherwise `ERR_OPEN_COLLECTIONS_CASES` (HTTP 409), and when no payment plan under the year's accounts is still `ACTIVE`, otherwise `ERR_ACTIVE_PAYMENT_PLANS` (HTTP 409). Closing sets `status` to `CLOSED`, blocks all further enrollment, assessment, and payment writes for the year, and increments the year's version by 1. `CLOSED` is terminal.

Fee catalog items retire when no longer offered: retiring moves an item `ACTIVE` → `RETIRED` and blocks new assessments against it, but only when no assessment referencing the item is in `ASSESSED`, `PARTIALLY_PAID`, `PAYMENT_PLAN`, or `DELINQUENT` status — assessments that are `PAID`, `REFUNDED`, `WAIVED`, or `VOID` do not block retirement. A retire attempt against an in-use item is rejected with `ERR_FEE_ITEM_IN_USE` (HTTP 409).

### 3.2. Students, Accounts, and the Family Balance

A `Bookkeeper` registers each **student** with an external_ref (the district SIS identifier, globally unique), a full_name, a grade_level from 9 to 12 — grade 12 students are graduation candidates — and a family_id grouping siblings. A student is born `ENROLLED` and ends either `WITHDRAWN` or `GRADUATED`. The student list read accepts a family_id filter.

Graduation is gated. Moving a student `ENROLLED` → `GRADUATED` requires grade_level exactly 12 — any other grade is rejected with `ERR_NOT_GRADUATION_CANDIDATE` (HTTP 422) — and requires that no account of the student for the current year holds posture `GRADUATION_HOLD` or `COLLECTIONS`, otherwise `ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION` (HTTP 409). A successful graduation sets `status` to `GRADUATED` and increments the student's version by 1. Withdrawal, the other terminal path, is a cascading event covered in §3.7.

For each school year, a `Bookkeeper` opens a **student account** for a student by supplying student_id. The account records its owning school_year_id and student_id and initializes every aggregate to zero with posture `CLEAR`. The aggregates are computed, never stored by hand:

- assessed_cents — the sum of assessed_amount_cents over the account's fee assessments in `ASSESSED`, `PARTIALLY_PAID`, `PAID`, `PAYMENT_PLAN`, `DELINQUENT`, or `WAIVED` status, plus the sum of allocated_cents over `REFUNDED` assessments (a refunded assessment contributes only the retained portion the school kept); `VOID` assessments contribute nothing.
- waived_cents — the sum of waived_amount_cents over all non-`VOID` assessments of the account.
- paid_cents — the sum of amount_cents over `SUCCEEDED` payments on the account, minus the refund_cents of `EXECUTED` refunds on the account. Unallocated overpayment is included, so a credit balance drives this above what was owed and balance_cents goes negative.
- balance_cents — assessed_cents minus waived_cents minus paid_cents; positive means the family owes, negative means the school owes the family a credit.
- family_balance_cents — the sum of balance_cents over all accounts whose student shares this student's family_id and whose school year is `OPEN`. Every sibling account computes the identical family total.

The account's posture is recomputed on every aggregate mutation — assessment create or void, waiver apply or revoke, payment settle, refund execute, write-off, aging sweep — and follows a fixed priority. If the account has a collections case in `WRITTEN_OFF` status, posture is `WRITTEN_OFF`. Otherwise, if the account has a case `OPEN` or `PAYMENT_PROMISED`, posture is `COLLECTIONS`. Otherwise, when the amount owed — a positive balance_cents — is strictly greater than the year's graduation_hold_threshold_cents, posture is `GRADUATION_HOLD`; an amount exactly equal to the threshold does not hold. Otherwise posture is `CLEAR`. Each recompute stamps last_posture_check_at with the logical clock's current instant. Reading an account directly may fire these lazy posture and aging recomputes on demand.

A computed summary read on the account returns its balance_cents, family_balance_cents, posture, assessed_cents, waived_cents, paid_cents, and open_case_count in one payload. The account list read filters by student_id or posture; a reverse lookup lists all accounts of a student across years.

### 3.3. Offerings and the Enrollment Lifecycle

An **offering** is a schedulable course or activity. Creating one takes a kind of `COURSE` or `ACTIVITY`, a title, the revenue-receiving department_id, the fee_item_id whose fee is assessed per enrollment, a start_date, an end_date at or after the start, and a capacity of at least 1 concurrently-enrolled students. Offerings are born `SCHEDULED`. When the logical clock's date reaches an offering's start_date while it is still `SCHEDULED`, the offering lazily moves `SCHEDULED` → `IN_SESSION` — observed on any read of the offering or on an operations run — and its version increments by 1. The offering list read filters by department_id or status.

Completing an offering moves it `IN_SESSION` → `COMPLETED`, cascades every `ACTIVE` enrollment on it to `COMPLETED`, and increments the offering's version by 1; completing requires the offering to actually be `IN_SESSION`, else `ERR_INVALID_STATE` (HTTP 409). Cancelling is available from either non-terminal working state, with a critical asymmetry detailed in §3.7: cancelling a `SCHEDULED` offering treats the fee as cancelled before start, while cancelling an `IN_SESSION` offering prorates by the days elapsed at cancellation. Either way, every `ACTIVE` enrollment on the offering becomes `DROPPED_BY_CANCELLATION`, each spawning a `PENDING` refund with reason `ACTIVITY_CANCELLATION`, and the offering's version increments by 1. A `COMPLETED` or already-`CANCELLED` offering accepts neither action.

**Enrollment** is where money first appears. A `Bookkeeper` enrolls an account's student into an offering by supplying offering_id. The checks run in the ladder order of §2.10: the year must be `OPEN`; the offering must exist in the same year; then the four enrollment business rules — no second `ACTIVE` enrollment for the same account and offering (`ERR_DUPLICATE_ENROLLMENT`, HTTP 409), the offering's `ACTIVE` enrollment count below capacity (`ERR_OFFERING_FULL`, HTTP 409), the offering still `SCHEDULED` since students cannot join an `IN_SESSION`, `COMPLETED`, or `CANCELLED` offering (`ERR_ENROLLMENT_WINDOW_CLOSED`, HTTP 409), and finally the half-open schedule-conflict check against the windows of every other offering actively enrolled on the same account, where touching boundaries do not collide (`ERR_SCHEDULE_CONFLICT`, HTTP 409).

A successful enrollment stamps enrolled_at from the logical clock, leaves withdrawn_at null, and immediately auto-creates the fee assessment: a FeeAssessment row in `ASSESSED` status whose assessed_amount_cents pins the catalog item's amount_cents at assessment time — later catalog price changes do not touch existing assessments — whose enrollment_id points back to the enrollment, and whose department_id resolves to the offering's department_id when enrollment-linked (offering-level attribution wins over the fee item's default department). If the account holds approved waiver applications, provisional waiver stacking runs against the new assessment (§3.4). The account's aggregates recompute at once.

Withdrawing a single enrollment moves it `ACTIVE` → `WITHDRAWN` and requires the enrollment to be `ACTIVE` and the school year `OPEN`. It stamps withdrawn_at from the logical clock, spawns a `PENDING` refund with reason `WITHDRAWAL` against the enrollment's fee assessment when the fee item is refundable — the amount computed by the proration rules of §3.7 — and recomputes the account's derived fields and posture, incrementing the account's version by 1. The enrollment list read filters by offering_id or status; reverse lookups list the enrollments of an offering (filterable by status) and the assessments spawned by an enrollment.

### 3.4. Fee Waivers: Programs, Applications, and the Stacking Waterfall

A **waiver program** is year-scoped configuration: a name such as "Free Lunch Waiver", a waiver_pct_bp from 1 to 10000 expressing the waived percentage of the post-prior-waiver base, a stacking_priority controlling application order (lower applies first, ties broken by the program's created_at ascending), a max_waived_per_student_cents cap of at least 0 limiting the program's total waived cents per student per year, and an inclusive eligibility band from eligibility_grade_min to eligibility_grade_max, where the maximum must be at least the minimum. Programs are born `ACTIVE`; suspending moves one to `SUSPENDED`, which blocks new approvals while leaving existing approvals in force. The program list read filters by status.

A **waiver application** is family-initiated: a `FamilyMember` submits one against an account with a waiver_program_id, the server records the submitter's `X-User-ID` as submitted_by_user_id, and the application sits `PENDING`. Review is the `Bookkeeper`'s, and it is guarded three ways. Approval requires the program to be `ACTIVE` — approving against a `SUSPENDED` program fails with `ERR_WAIVER_PROGRAM_SUSPENDED` (HTTP 409) — and requires expected_account_version matching the account's current version per §2.9, else `ERR_STALE_VERSION` (HTTP 412). The segregation-of-duties check runs before the eligibility check per the ladder: the reviewer's `X-User-ID` must differ from submitted_by_user_id, else `ERR_WAIVER_SELF_APPROVAL` (HTTP 403); then the student's grade_level must fall within the program's inclusive band, else `ERR_WAIVER_INELIGIBLE` (HTTP 422). A successful approval moves the application `PENDING` → `APPROVED`, stamps reviewed_by_user_id with the reviewer's `X-User-ID`, runs the final waiver stacking below, recomputes the account, and increments the account's version by 1. Denial moves `PENDING` → `DENIED`, requires only that the denier differ from the submitter (the same `ERR_WAIVER_SELF_APPROVAL` guard), and stamps reviewed_by_user_id. Revoking an `APPROVED` application requires the revoker's `X-User-ID` to differ from submitted_by_user_id (again `ERR_WAIVER_SELF_APPROVAL`) and rolls the program out of the stacking as described below, moving the application to `REVOKED`; applications that were never approved cannot be revoked. `APPROVED`, `DENIED`, and `REVOKED` are all terminal. The application list read filters by status or waiver_program_id; a reverse lookup lists all applications to a program.

The **waiver stacking** calculation runs on approval, on revocation, and — provisionally — whenever a new assessment is created on an account holding approved applications. The approved programs for the account are sorted by stacking_priority ascending, ties broken by program created_at ascending. Each waiverable assessment in `ASSESSED` or `PARTIALLY_PAID` status is then visited; assessments on non-waiverable fee items are skipped entirely. For each visited assessment, the base is the unpaid remainder: assessed_amount_cents minus allocated_cents. Programs apply to that base in sorted order, each shrinking what the next sees. For each program, the tentative waiver is the remaining base times the program's waiver_pct_bp divided by ten thousand, **rounded down to a whole cent first**; the result is then capped at the smaller of two limits — the program's remaining per-student allowance and the remaining base itself. The remaining allowance is max_waived_per_student_cents minus the cents this program has already waived across the account's other assessments, where earlier-created assessments consume the cap first in created_at ascending order. The capped amount is added to the assessment's waived_amount_cents and subtracted from the remaining base before the next program applies. This floor-then-cap order is pinned: truncating before the cap produces different cents than capping before truncating, and only the former is correct.

On approval or revocation the stacking is **final**: every program's contribution is recomputed from scratch against current unpaid remainders, and differences land as deltas on each assessment's waived_amount_cents. On assessment creation the stacking is **provisional**: because allocated_cents is zero at creation, the waiver computes against the full assessed_amount_cents, and if a payment settles before the next approval or revocation, the provisional base can differ from the post-payment base until that final recomputation. Revocation recomputes without the revoked program: waived amounts roll back, and an assessment that loses its full coverage returns from `WAIVED` to `ASSESSED` — or to `PARTIALLY_PAID` when payments have already landed — per the remaining obligation.

An assessment whose waiver coverage reaches its full assessed_amount_cents transitions `ASSESSED` → `WAIVED` with waived_amount_cents set to the entire assessed amount; `WAIVED` is terminal. Every stacking event recomputes the account's waived_cents and balance_cents and refreshes posture.

### 3.5. Taking Money: Payments, Purchases, and the Allocation Waterfall

Before money moves, there must be something to pay. Beyond enrollment-driven assessments, a `Bookkeeper` may create an **ad-hoc fee assessment** on an account with a fee_item_id and an explicit assessed_amount_cents greater than zero; its enrollment_id stays null, its department_id resolves to the catalog item's default department, provisional waiver stacking applies on creation (§3.4), and the account recomputes. Every assessment carries allocated_cents (payments applied, initially 0), refunded_cents (refunds sourced from it, initially 0), and a computed outstanding_cents — the assessed amount minus waived minus allocated. A `Bookkeeper` may void an assessment only while it is still `ASSESSED` and completely untouched: allocated_cents and refunded_cents must both be zero, otherwise `ERR_ASSESSMENT_HAS_ACTIVITY` (HTTP 409); a voided assessment is excluded from all account aggregates and the account recomputes. The assessment list read filters by status or department_id.

A **payment** is initiated by a `FamilyMember` with an amount_cents greater than zero, a method of `CARD`, `ACH`, `CASH`, or `CHECK`, and a client-supplied idempotency_key that must be unique per account among payments that are not `FAILED` — a reused key is rejected with `ERR_DUPLICATE_PAYMENT` (HTTP 409). The optional overpayment_policy is `CREDIT_BALANCE` when omitted, meaning excess money becomes a negative (credit) balance, or `REJECT`, meaning an amount beyond the allocatable outstanding is refused. Payments are born `PENDING` and end `SUCCEEDED`, `FAILED`, or `VOIDED`. A `Bookkeeper` may void a `PENDING` payment (`VOIDED`); the payment list read filters by status.

Settlement is the gateway callback, performed by a `FamilyMember` supplying an outcome. Settling requires the payment to be `PENDING`, else `ERR_INVALID_STATE`, and refuses accounts in `WRITTEN_OFF` posture with `ERR_ACCOUNT_WRITTEN_OFF` (HTTP 409). An outcome of `FAILED` moves the payment to `FAILED` and writes nothing — no allocations, no ledger rows. An outcome of `SUCCEEDED` runs the **allocation waterfall**, which is the heart of the money flow:

- **Stage 1 — installment due.** When the account has an `ACTIVE` payment plan, the waterfall walks the plan's installments ordered by due_date ascending, then sequence ascending. For each installment still short — paid_cents below its amount_cents — it takes the smaller of the money remaining and the installment's shortfall. That take is spread across the plan's covered assessments proportionally to their outstanding obligations captured at plan creation (creation-time snapshot weights, frozen even as balances later move). Each per-assessment share is rounded half-up to a whole cent, and any residual cent of over- or under-allocation after rounding lands on the covered assessment with the earliest created_at. Each share writes a PaymentAllocation row recording its payment_id, its fee_assessment_id, the allocated_cents of the share, and allocation_rule `INSTALLMENT_DUE`; the installment's paid_cents grows by the take, and the remaining money shrinks accordingly.
- **Stage 2 — oldest outstanding.** Whatever remains flows to the account's fee assessments that have outstanding_cents above zero and status `ASSESSED`, `PARTIALLY_PAID`, or `DELINQUENT`, ordered by created_at ascending, ties broken by assessed_amount_cents descending, and any further tie resolved by created_at ascending again — identifiers are never consulted. Assessments in `PAYMENT_PLAN` status are reachable only through stage 1, never here. Each visited assessment takes the smaller of the money remaining and its outstanding_cents, writing a PaymentAllocation row — again keyed by payment_id and fee_assessment_id with the take as its allocated_cents — with allocation_rule `OLDEST_OUTSTANDING`.
- **Stage 3 — overpayment.** If money still remains: under the `REJECT` policy the entire settle is refused with `ERR_OVERPAYMENT_REJECTED` (HTTP 402); under `CREDIT_BALANCE` the remainder stays unallocated and flows into balance_cents as a negative credit through the paid_cents recompute.

The `REJECT` check is a pre-check with atomicity: when the policy is `REJECT`, the allocatable ceiling — stage-1 installment capacity plus stage-2 outstanding — is computed up front, an amount_cents above that ceiling is rejected before any allocation row is written, and the payment stays unsettled.

Allocations move assessment state. An allocation that covers some but not all of an assessment's outstanding moves it `ASSESSED` → `PARTIALLY_PAID`. When allocations plus waivers reach the full assessed_amount_cents, the assessment becomes `PAID` — straight from `ASSESSED` on a single covering allocation, from `PARTIALLY_PAID` on the completing allocation, from `PAYMENT_PLAN` when the final installment settles (which also clears the assessment's payment_plan_id), or from `DELINQUENT` when a late payment settles it — in that last case any linked `OPEN` or `PAYMENT_PROMISED` collections case re-evaluates and may resolve (§3.8). The payment's own allocated_cents is the sum of its allocation rows. Every allocation also writes a `DISTRIBUTION_CREDIT` ledger entry for its assessment's department_id, tagged with the payment's source_payment_id. Settlement then recomputes the account's paid_cents, balance_cents, and family_balance_cents, refreshes posture — which may clear a `GRADUATION_HOLD` or resolve a collections case — and increments the account's version by 1. Allocation rows are readable per payment and per assessment.

**Purchases** of optional items run on the disjoint purchase ledger of §2.11. A `FamilyMember` buys by supplying item_id and a method; the item's sold_count must be below its inventory_cap, else `ERR_ITEM_SOLD_OUT` (HTTP 409). The purchase charges atomically at creation: the Purchase row is created directly in `COMPLETED` status with amount_cents pinned from the item's price at purchase time, a `DISTRIBUTION_CREDIT` ledger entry lands on the item's department, and sold_count increments by 1. Should the charge fail or be voided before completion, the row instead moves `PENDING` → `VOID` with no ledger effect. A purchase's refunded_cents tracks refunds sourced from it, starting at 0. The purchase list read filters by item_id or status; a reverse lookup lists all purchases of an item. Purchase money never enters assessed_cents, paid_cents, or balance_cents.

### 3.6. Payment Plans and Installments

When a balance is large, a `Bookkeeper` opens a **payment plan** over the account's outstanding. The request carries installment_count, a first_due_date that must not precede the current logical date, an interval_days greater than 0, and the concurrency guard expected_account_version (§2.9) — a stale account version fails with `ERR_STALE_VERSION` (HTTP 412) before anything is created.

The covered set is not negotiable: all of the account's assessments in `ASSESSED` or `PARTIALLY_PAID` status with `outstanding_cents` above zero, ordered by `created_at` ascending — the plan covers the account's full outstanding and there is no cherry-picking. The plan's covered_amount_cents is the sum of those outstanding amounts at creation. The terms must hold or creation fails with `ERR_PLAN_TERMS_VIOLATION` (HTTP 422): the covered total must be at least the year's payment_plan_min_cents, the installment_count must lie between 2 and the year's payment_plan_max_installments inclusive, and there must be outstanding to cover at all.

The **installment schedule** divides with a pinned remainder. The per-installment base is covered_amount_cents divided by installment_count, rounded down to a whole cent; the remainder — the covered total minus the base times the count — is added in full to the **last** installment, never the first. Installments are numbered from 1 upward in their sequence, and each installment's due_date is first_due_date advanced by interval_days once for every preceding installment — the first installment falls due exactly on first_due_date, the second one interval later, and so on; the plan's installment_amount_cents records the per-installment base. Creation moves every covered assessment `ASSESSED` or `PARTIALLY_PAID` → `PAYMENT_PLAN` and sets each one's payment_plan_id, creates all installments in `SCHEDULED` status, and increments the account's version by 1. The plan list and installment list reads each filter by status; reverse lookups list a plan's installments and the assessments a plan covers.

Installments live a small lifecycle of their own. `SCHEDULED` → `DUE` fires lazily when the logical clock reaches the due_date (observed on an operations run or an account read). The waterfall can pay an installment from `SCHEDULED` (early payment is allowed), from `DUE`, or from `PAST_DUE` (the recovery loop); a fully covered installment becomes `PAID`, and when the last installment is paid the plan completes. The aging sweep moves a `DUE` installment to `PAST_DUE` when the logical date has passed its due_date with paid_cents still short of amount_cents, triggering a case bucket recompute. From any of `SCHEDULED`, `DUE`, or `PAST_DUE`, an installment becomes `WAIVED_BY_DEFAULT` when its plan defaults or is cancelled.

A plan completes `ACTIVE` → `COMPLETED` when every installment is `PAID`; its covered assessments move `PAYMENT_PLAN` → `PAID` with their payment_plan_id cleared, and the account recomputes. A plan defaults when the aging sweep finds any installment `PAST_DUE` for more than aging_interval_days days past its due date: the plan moves `ACTIVE` → `DEFAULTED`, its unpaid installments become `WAIVED_BY_DEFAULT`, every covered assessment becomes `DELINQUENT`, a collections case opens for the account (or the existing case's bucket advances), and posture recomputes. A `Bookkeeper` may cancel an `ACTIVE` plan only while no installment is `PAID` — a plan with any paid installment refuses with `ERR_PLAN_HAS_PAYMENTS` (HTTP 409); cancellation moves the plan to `CANCELLED`, waives its unpaid installments to `WAIVED_BY_DEFAULT`, and returns the covered assessments from `PAYMENT_PLAN` to `ASSESSED` so the obligation flows back through the normal waterfall.

### 3.7. Withdrawals, Cancellations, and Refunds

Leaving early unwinds money. The unwind amounts are governed by the **refund proration** rules, which measure days elapsed from the offering's start. The day count is the logical clock's date minus the offering's start_date, in whole days, rounded down; for an offering cancelled while still `SCHEDULED`, the elapsed count is zero regardless of the date. Only collected cents are refundable — the assessment's allocated_cents — and waived portions are never refunded. If the fee item's refundable flag is false, the refund computes to zero. Otherwise the tier boundaries are inclusive at both edges: when the elapsed days do not exceed the year's refund_full_days, the tier is full and the refund equals everything collected toward the assessment; when the elapsed days exceed refund_full_days but do not exceed refund_partial_days, the tier is partial and the refund is the collected amount times partial_refund_pct_bp divided by ten thousand, rounded down to a whole cent; beyond refund_partial_days, the refund is zero.

Withdrawing a single enrollment (§3.3) spawns a `PENDING` refund with reason `WITHDRAWAL` against the enrollment's assessment when the fee item is refundable, the amount prorated at the withdrawal date; refunds only arise when the withdrawal happens while the enrollment is `ACTIVE`. Cancelling an offering spawns one `PENDING` refund with reason `ACTIVITY_CANCELLATION` per dropped enrollment: a `SCHEDULED` offering's cancellation always lands in the full tier because the fee was cancelled before start, while an `IN_SESSION` offering's cancellation prorates at the cancellation date.

Withdrawing the whole **student** is a depth-3 cascade executed by a `Bookkeeper`. It is refused while any account of the student holds posture `COLLECTIONS` — `ERR_STUDENT_IN_COLLECTIONS` (HTTP 409). Otherwise: every `ACTIVE` enrollment on every account of the student moves to `WITHDRAWN`, each triggering its own proration refund exactly as a single-enrollment withdrawal; every `COMPLETED` purchase of a refundable item on the student's accounts spawns a `PENDING` refund with reason `WITHDRAWAL` for the full purchase amount; every `ACTIVE` payment plan on those accounts moves to `CANCELLED` with its `SCHEDULED` and `DUE` installments becoming `WAIVED_BY_DEFAULT`; and each affected account recomputes its posture. The student's version increments by 1, as does each affected account's.

A **refund** row records its student_account_id, its reason — one of `WITHDRAWAL`, `ACTIVITY_CANCELLATION`, `OVERPAYMENT_RETURN`, or `WRITE_OFF_REVERSAL` — the computed refund_cents, and its source: fee_assessment_id is set only for withdrawal or cancellation refunds on an enrollment fee, purchase_id only when sourced from a purchase, and both are null for an overpayment return. A `Bookkeeper` may also create an overpayment return manually against a credit balance by supplying amount_cents; the amount must be greater than zero and no more than the negation of the account's balance_cents — the size of the credit — else `ERR_INVALID_REQUEST` (HTTP 400), and the created refund sits `PENDING` with refund_cents set to exactly that amount, no proration involved. The refund list read filters by status or reason; reverse lookups list refunds sourced from an assessment or from a purchase.

Executing a refund moves it `PENDING` → `EXECUTED` and requires refund_cents above zero — a zero-valued refund cannot execute and is refused with `ERR_ZERO_REFUND` (HTTP 422). Execution splices by source. For assessment-sourced refunds (withdrawal or cancellation): the source assessment's allocated_cents drops by refund_cents, its refunded_cents grows by the same, and its status becomes `REFUNDED` from `PARTIALLY_PAID` or `PAID` — the obligation collapses to the retained portion (the post-reduction allocated_cents), which is exactly what assessed_cents continues to count for a `REFUNDED` row; `REFUNDED` is terminal and is reached only through this executed-refund path, never through payment. For purchase-sourced refunds: the purchase moves `COMPLETED` → `REFUNDED` and the item's sold_count decrements by 1. For overpayment returns there is no assessment or purchase linkage at all — only the account's paid_cents is reduced. Assessment- and purchase-sourced executions also write `DISTRIBUTION_REVERSAL` ledger entries (negative amounts) against the original departments. Every execution recomputes the account's paid_cents and balance_cents and refreshes posture. Denying a `PENDING` refund moves it to `DENIED` and changes nothing — no ledger, no assessment updates.

### 3.8. Collections, Write-Offs, and Year-End Reconciliation

Unpaid money ages. The **collections aging** machinery runs as the year-scoped operations sweep, which a `Bookkeeper` triggers; the run reports back swept_cases, defaulted_plans, advanced_installments, and opened_cases. Each collections case carries opened_at (the logical-clock instant the sweep opened it), a principal_cents snapshot of the balance owed at open, a computed aging_bucket, written_off_cents starting at 0, and an approved_writeoff_cents that stays 0 until `Superintendent` co-approval. Buckets are measured against the year's aging_interval_days — call it k. A case's age is the whole-day floor of the logical date minus opened_at. The age below k is `CURRENT`; at least k but below twice k is `BUCKET_1`; at least twice k but below three times k is `BUCKET_2`; three times k or more is `BUCKET_3`. Boundaries include the lower edge and exclude the upper.

The sweep applies its side effects in a fixed order. First, every `DUE` installment whose logical date has passed its due_date becomes `PAST_DUE`. Second, any `ACTIVE` plan with an installment `PAST_DUE` for more than k days past its due date defaults, cascading per §3.6. Third, every assessment still `ASSESSED` or `PARTIALLY_PAID` whose created_at is more than k days old with outstanding_cents above zero becomes `DELINQUENT`, and a collections case opens for the account — principal_cents snapshotting the balance owed — when no `OPEN` case exists, while an existing case instead advances its bucket. Fourth, a `PAYMENT_PROMISED` case with no `SUCCEEDED` payment created after the promise timestamp reverts to `OPEN` — the broken-promise loop.

Between sweeps, a `Bookkeeper` may record a payment promise, moving a case `OPEN` → `PAYMENT_PROMISED`; the case list read filters by status. Cases resolve themselves: whenever a payment settlement drives the account's balance_cents to zero or below, an `OPEN` or `PAYMENT_PROMISED` case becomes `RESOLVED` and posture recomputes, clearing `COLLECTIONS`.

Writing off a case is the most guarded operation in the system, and its three gates run in ladder order. The case must have aged to `BUCKET_3`, else `ERR_CASE_NOT_AGED` (HTTP 409). When the requested amount_cents exceeds the year's writeoff_max_cents, the case's approved_writeoff_cents must cover the requested amount — that coverage is the `Superintendent`'s co-approval, recorded by supplying approved_writeoff_cents — else `ERR_WRITEOFF_NEEDS_APPROVAL` (HTTP 403). And the write-off actor's `X-User-ID` must differ from the identifier that recorded the most recent `SUCCEEDED` payment on the account, when such a payment exists, else `ERR_WRITEOFF_SOD` (HTTP 403). A write-off may execute from `OPEN` or `PAYMENT_PROMISED`, with identical gates and effects.

Executing the write-off sets the case's written_off_cents to the amount and moves the case to `WRITTEN_OFF`. It writes a `WRITE_OFF_DEBIT` ledger entry against each department holding outstanding distributed cents for the account, prorating the write-off by each department's share of the account's outstanding: every department's share is rounded down to a whole cent, and the leftover cent goes to the department whose ledger entry for this account has the earliest created_at. The account's posture becomes `WRITTEN_OFF` and the family balance recomputes; every assessment still `DELINQUENT` or `ASSESSED` under the case moves to `VOID`, its obligation zeroed through the write-off ledger so the reconciliation invariant holds. From then on, payment settlement against the account is refused with `ERR_ACCOUNT_WRITTEN_OFF`.

**Reconciliation** closes the loop between the two views of departmental money. A `Bookkeeper` triggers a run for the year; the run is atomic, born directly into its single terminal state `COMPLETED`, and stamps run_at from the logical clock. Every ledger entry whose reconciliation_run_id is still null is stamped with the run's id, and the run's entries_reconciled counts them. Then, per department, the run compares two derivations. The expected figure is gross: the sum of PaymentAllocation allocated_cents over `SUCCEEDED` payments targeting that department's assessments — immutable rows, never netted — plus the amount_cents of purchases `COMPLETED` or `REFUNDED` on the department's items, minus the refund_cents of `EXECUTED` refunds sourced from the department's assessments or purchases, minus the `WRITE_OFF_DEBIT` cents against the department. The actual figure is the department's ledger-derived distributed_cents. When any department's two figures differ, the run's drift_detected is true; either way each department's reconciled_cents advances to its actual figure and unreconciled_cents recomputes. The invariant the run verifies is exact and holds after every mutation: the sum of all departments' distributed_cents equals the sum of allocations over succeeded payments, plus the sum of purchase amounts over completed and refunded purchases, minus the sum of executed refunds, minus the sum of written_off_cents across cases. Ledger reads filter by department_id or entry_type, and reverse lookups expose the entries of a department, of a payment, or of a reconciliation run, as well as the runs of a year.

## 4. Endpoint Definitions

Endpoints that create a new resource — a school year, department, fee item, purchase item, offering, student, account, enrollment, assessment, purchase, waiver program, waiver application, payment, payment plan, refund, or reconciliation run — return `201 Created`. Actions on existing resources (open, close, retire, complete, cancel, withdraw, graduate, approve, deny, revoke, settle, void, execute, promise, approve-writeoff, write-off, suspend, operations runs, and the clock) return `200 OK`, as do all reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | Bookkeeper |
| POST | `/school-years` | Create a school year (DRAFT) | Bookkeeper |
| GET | `/school-years` | List school years | Any |
| GET | `/school-years/{id}` | Get a school year | Any |
| POST | `/school-years/{id}/open` | Open a DRAFT year | Bookkeeper |
| POST | `/school-years/{id}/close` | Close an OPEN year (OCC-guarded) | Bookkeeper |
| POST | `/school-years/{id}/ops-runs` | Run the aging/posture sweep for the year | Bookkeeper |
| POST | `/school-years/{id}/departments` | Create a department | Bookkeeper |
| GET | `/school-years/{id}/departments` | List departments for a year | Any |
| GET | `/school-years/{id}/departments/{departmentId}` | Get a department | Any |
| POST | `/school-years/{id}/fee-catalog-items` | Create a fee catalog item | Bookkeeper |
| GET | `/school-years/{id}/fee-catalog-items` | List fee catalog items | Any |
| GET | `/school-years/{id}/fee-catalog-items/{itemId}` | Get a fee catalog item | Any |
| POST | `/school-years/{id}/fee-catalog-items/{itemId}/retire` | Retire an unused fee item | Bookkeeper |
| POST | `/school-years/{id}/optional-purchase-items` | Create an optional purchase item | Bookkeeper |
| GET | `/school-years/{id}/optional-purchase-items` | List optional purchase items | Any |
| GET | `/school-years/{id}/optional-purchase-items/{itemId}` | Get an optional purchase item | Any |
| POST | `/school-years/{id}/offerings` | Create a course/activity offering | Bookkeeper |
| GET | `/school-years/{id}/offerings` | List offerings | Any |
| GET | `/school-years/{id}/offerings/{offeringId}` | Get an offering | Any |
| POST | `/school-years/{id}/offerings/{offeringId}/complete` | Complete an IN_SESSION offering | Bookkeeper |
| POST | `/school-years/{id}/offerings/{offeringId}/cancel` | Cancel an offering; spawns prorated refunds | Bookkeeper |
| POST | `/students` | Register a student | Bookkeeper |
| GET | `/students` | List students | Any |
| GET | `/students/{id}` | Get a student | Any |
| POST | `/students/{id}/withdraw` | Withdraw a student (cascade: enrollments → refunds; plans cancelled) | Bookkeeper |
| POST | `/students/{id}/graduate` | Graduate a grade-12 student (hold-gated) | Bookkeeper |
| POST | `/school-years/{id}/student-accounts` | Open a student account for the year | Bookkeeper |
| GET | `/school-years/{id}/student-accounts` | List accounts for a year | Any |
| GET | `/student-accounts/{id}` | Get an account (computed aggregates) | Any |
| GET | `/student-accounts/{id}/summary` | Computed read: balance breakdown, family balance, posture explanation | Any |
| POST | `/student-accounts/{id}/enrollments` | Enroll the account's student into an offering; auto-creates the fee assessment and auto-applies approved waivers | Bookkeeper |
| GET | `/student-accounts/{id}/enrollments` | List enrollments for an account | Any |
| GET | `/student-accounts/{id}/enrollments/{enrollmentId}` | Get an enrollment | Any |
| POST | `/student-accounts/{id}/enrollments/{enrollmentId}/withdraw` | Withdraw an enrollment (spawns prorated refund) | Bookkeeper |
| POST | `/student-accounts/{id}/fee-assessments` | Ad-hoc fee assessment (no enrollment) | Bookkeeper |
| GET | `/student-accounts/{id}/fee-assessments` | List assessments for an account | Any |
| GET | `/student-accounts/{id}/fee-assessments/{assessmentId}` | Get an assessment | Any |
| POST | `/student-accounts/{id}/fee-assessments/{assessmentId}/void` | Void an untouched ASSESSED assessment | Bookkeeper |
| POST | `/student-accounts/{id}/purchases` | Purchase an optional item (charged atomically) | FamilyMember |
| GET | `/student-accounts/{id}/purchases` | List purchases for an account | Any |
| GET | `/student-accounts/{id}/purchases/{purchaseId}` | Get a purchase | Any |
| POST | `/school-years/{id}/waiver-programs` | Create a waiver program | Bookkeeper |
| GET | `/school-years/{id}/waiver-programs` | List waiver programs | Any |
| GET | `/school-years/{id}/waiver-programs/{programId}` | Get a waiver program | Any |
| POST | `/school-years/{id}/waiver-programs/{programId}/suspend` | Suspend a program (blocks new approvals; existing approvals remain) | Bookkeeper |
| POST | `/student-accounts/{id}/waiver-applications` | Submit a waiver application (family-initiated) | FamilyMember |
| GET | `/student-accounts/{id}/waiver-applications` | List waiver applications for an account | Any |
| GET | `/student-accounts/{id}/waiver-applications/{applicationId}` | Get a waiver application | Any |
| POST | `/student-accounts/{id}/waiver-applications/{applicationId}/approve` | Approve application (OCC-guarded; runs waiver stacking) | Bookkeeper |
| POST | `/student-accounts/{id}/waiver-applications/{applicationId}/deny` | Deny application | Bookkeeper |
| POST | `/student-accounts/{id}/waiver-applications/{applicationId}/revoke` | Revoke an approved application (rolls back waivers) | Bookkeeper |
| POST | `/student-accounts/{id}/payments` | Initiate an online payment | FamilyMember |
| GET | `/student-accounts/{id}/payments` | List payments for an account | Any |
| GET | `/student-accounts/{id}/payments/{paymentId}` | Get a payment | Any |
| POST | `/student-accounts/{id}/payments/{paymentId}/settle` | Settle a PENDING payment (gateway callback simulation) | FamilyMember |
| POST | `/student-accounts/{id}/payments/{paymentId}/void` | Void a PENDING payment | Bookkeeper |
| GET | `/student-accounts/{id}/payments/{paymentId}/allocations` | List allocation rows for a payment | Any |
| POST | `/student-accounts/{id}/payment-plans` | Open a payment plan over the account's outstanding (OCC-guarded) | Bookkeeper |
| GET | `/student-accounts/{id}/payment-plans` | List payment plans for an account | Any |
| GET | `/student-accounts/{id}/payment-plans/{planId}` | Get a payment plan | Any |
| GET | `/student-accounts/{id}/payment-plans/{planId}/installments` | List installments for a plan | Any |
| POST | `/student-accounts/{id}/payment-plans/{planId}/cancel` | Cancel an ACTIVE plan with no paid installments | Bookkeeper |
| POST | `/student-accounts/{id}/refunds` | Manually create an OVERPAYMENT_RETURN refund against a credit balance | Bookkeeper |
| GET | `/student-accounts/{id}/refunds` | List refunds for an account | Any |
| GET | `/student-accounts/{id}/refunds/{refundId}` | Get a refund | Any |
| POST | `/student-accounts/{id}/refunds/{refundId}/execute` | Execute a PENDING refund | Bookkeeper |
| POST | `/student-accounts/{id}/refunds/{refundId}/deny` | Deny a PENDING refund | Bookkeeper |
| GET | `/student-accounts/{id}/ledger-entries` | List ledger entries for an account | Any |
| POST | `/school-years/{id}/reconciliation-runs` | Run reconciliation: stamp unreconciled ledger rows, compute drift, advance reconciled counters | Bookkeeper |
| GET | `/student-accounts/{id}/collections-cases` | List collections cases for an account | Any |
| GET | `/student-accounts/{id}/collections-cases/{caseId}` | Get a collections case | Any |
| POST | `/student-accounts/{id}/collections-cases/{caseId}/promise` | Record a payment promise on an OPEN case | Bookkeeper |
| POST | `/student-accounts/{id}/collections-cases/{caseId}/approve-writeoff` | Superintendent authorizes a write-off amount above the bookkeeper limit | Superintendent |
| POST | `/student-accounts/{id}/collections-cases/{caseId}/write-off` | Execute write-off on a BUCKET_3 case | Bookkeeper |
| GET | `/departments/{id}` | Get a department by id (flat alias) | Any |
| GET | `/offerings/{id}` | Get an offering by id (flat alias) | Any |
| GET | `/fee-catalog-items/{id}` | Get a fee catalog item by id (flat alias) | Any |
| GET | `/optional-purchase-items/{id}` | Get an optional purchase item by id (flat alias) | Any |
| GET | `/enrollments/{id}` | Get an enrollment by id (flat alias) | Any |
| GET | `/fee-assessments/{id}` | Get a fee assessment by id (flat alias) | Any |
| GET | `/purchases/{id}` | Get a purchase by id (flat alias) | Any |
| GET | `/waiver-programs/{id}` | Get a waiver program by id (flat alias) | Any |
| GET | `/waiver-applications/{id}` | Get a waiver application by id (flat alias) | Any |
| GET | `/payments/{id}` | Get a payment by id (flat alias) | Any |
| GET | `/payment-plans/{id}` | Get a payment plan by id (flat alias) | Any |
| GET | `/refunds/{id}` | Get a refund by id (flat alias) | Any |
| GET | `/reconciliation-runs/{id}` | Get a reconciliation run by id (flat alias) | Any |
| GET | `/students/{id}/student-accounts` | List accounts for a student | Any |
| GET | `/departments/{id}/offerings` | List offerings of a department | Any |
| GET | `/fee-catalog-items/{id}/offerings` | List offerings using a fee item | Any |
| GET | `/departments/{id}/fee-catalog-items` | List fee items of a department | Any |
| GET | `/departments/{id}/optional-purchase-items` | List purchase items of a department | Any |
| GET | `/offerings/{id}/enrollments` | List enrollments in an offering | Any |
| GET | `/enrollments/{id}/fee-assessments` | List assessments spawned by an enrollment | Any |
| GET | `/fee-catalog-items/{id}/fee-assessments` | List assessments of a fee item | Any |
| GET | `/departments/{id}/fee-assessments` | List assessments attributed to a department | Any |
| GET | `/payment-plans/{id}/fee-assessments` | List assessments covered by a plan | Any |
| GET | `/optional-purchase-items/{id}/purchases` | List purchases of an item | Any |
| GET | `/waiver-programs/{id}/waiver-applications` | List applications to a program | Any |
| GET | `/payments/{id}/allocations` | List allocation rows of a payment | Any |
| GET | `/fee-assessments/{id}/payment-allocations` | List allocation rows targeting an assessment | Any |
| GET | `/payment-plans/{id}/installments` | List installments of a plan | Any |
| GET | `/fee-assessments/{id}/refunds` | List refunds sourced from an assessment | Any |
| GET | `/purchases/{id}/refunds` | List refunds sourced from a purchase | Any |
| GET | `/departments/{id}/ledger-entries` | List ledger entries of a department | Any |
| GET | `/payments/{id}/ledger-entries` | List ledger entries produced by a payment | Any |
| GET | `/reconciliation-runs/{id}/ledger-entries` | List ledger entries stamped by a run | Any |
| GET | `/school-years/{id}/reconciliation-runs` | List reconciliation runs of a year | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_YEAR_NOT_CONFIGURABLE` | 409 Conflict |
| `ERR_OPEN_COLLECTIONS_CASES` | 409 Conflict |
| `ERR_ACTIVE_PAYMENT_PLANS` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_OFFERING_FULL` | 409 Conflict |
| `ERR_ENROLLMENT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_YEAR_OVERLAP` | 409 Conflict |
| `ERR_STUDENT_IN_COLLECTIONS` | 409 Conflict |
| `ERR_NOT_GRADUATION_CANDIDATE` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION` | 409 Conflict |
| `ERR_FEE_ITEM_IN_USE` | 409 Conflict |
| `ERR_ASSESSMENT_HAS_ACTIVITY` | 409 Conflict |
| `ERR_WAIVER_PROGRAM_SUSPENDED` | 409 Conflict |
| `ERR_WAIVER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_WAIVER_SELF_APPROVAL` | 403 Forbidden |
| `ERR_DUPLICATE_PAYMENT` | 409 Conflict |
| `ERR_OVERPAYMENT_REJECTED` | 402 Payment Required |
| `ERR_PLAN_TERMS_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PLAN_HAS_PAYMENTS` | 409 Conflict |
| `ERR_ITEM_SOLD_OUT` | 409 Conflict |
| `ERR_ZERO_REFUND` | 422 Unprocessable Entity |
| `ERR_CASE_NOT_AGED` | 409 Conflict |
| `ERR_WRITEOFF_NEEDS_APPROVAL` | 403 Forbidden |
| `ERR_WRITEOFF_SOD` | 403 Forbidden |
| `ERR_ACCOUNT_WRITTEN_OFF` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
