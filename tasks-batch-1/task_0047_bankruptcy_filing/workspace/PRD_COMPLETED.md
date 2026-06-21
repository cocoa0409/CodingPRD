# Bankruptcy Filing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Bankruptcy Filing API, a back-office system that administers consumer bankruptcy cases under both Chapter 7 (liquidation) and Chapter 13 (reorganization). The platform carries a case from its first DRAFT petition through the means test, the assembly of Schedules A through J, the petition that raises the automatic stay, the 341 creditors' meeting, the allowance of proofs of claim, the confirmation and funding of a Chapter 13 repayment plan, and finally the entry of discharge or dismissal.

Two concerns dominate the design. The first is the **automatic stay**, the statutory shield that arises the moment a petition is filed and that determines whether creditors may continue collection activity; the system models this as a derived posture on the case and gates creditor-facing operations against it. The second is a strict **segregation of duties**: the debtor who files a case and proposes a plan can never be the trustee who chairs the meeting, allows claims, confirms the plan, and grants discharge. The requirements below are written for the engineers building the service; they describe domain behavior first and the HTTP surface second.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Debtor`, `Trustee`, `Creditor`, and `BankruptcyAdmin`.

The first three roles are entity-backed, meaning the identity in `X-User-ID` is the primary key of a persisted registry record. When `X-User-Role` is `Debtor`, `X-User-ID` is the `id` of the acting `Debtor`; ownership checks on any resource that references a `Debtor` compare the resource's debtor foreign key to `X-User-ID`. When `X-User-Role` is `Creditor`, `X-User-ID` is the `id` of the acting `Creditor`; ownership checks on any resource that references a `Creditor` compare the resource's creditor foreign key to `X-User-ID`. When `X-User-Role` is `Trustee`, `X-User-ID` is the `id` of the acting `Trustee`; in particular, the rule that lets a trustee conduct a 341 meeting compares `X-User-ID` to the meeting's `trustee_id`, so that only the assigned trustee may chair it. By contrast, when `X-User-Role` is `BankruptcyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`; the admin role exists for registry bootstrap and oversight reads and never drives case adjudication.

This segregation is foundational. The debtor opens the case, submits the means test, files schedules and debts, and proposes Chapter 13 plans. The trustee schedules and chairs the meeting, allows or disallows claims, confirms or denies plans, applies trustee payments, rules on relief from the stay, and grants discharge or dismissal. A creditor files proofs of claim and moves for relief from the stay against its own collateral. No single actor may both file a case and adjudicate it.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by the resource's creation timestamp in ascending order — that is, by `created_at` from oldest to newest.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Audit Fields

Every persisted resource in the system — the case, the debtor, the means test, each schedule line, each debt, the creditor and trustee registries, the 341 meeting, each proof of claim, the plan, each plan payment, and each stay-relief motion — carries a server-minted `id`. This identifier is a UUID with no type prefix; it is identity only and is never an input to any business decision. Each resource also records a `created_at`, an ISO 8601 UTC timestamp with three fractional digits stamped when the row is first written.

All of these resources additionally carry an `updated_at` and a `version`. The `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that occur as a cascaded side effect of an operation on a different resource. The `version` is an integer that starts at 1 when the resource is created and increments by exactly one on each subsequent mutation. There are no resources in this system that omit `updated_at` or `version`; every entity participates in the full audit-field convention.

### 2.5. Hierarchical Consistency and Cascading Side Effects

The case is the aggregate root. Several of its fields are derived rather than directly supplied, and the system keeps them reconciled immediately as the underlying facts change. Whenever a derived field on the case is recomputed as the consequence of an operation — for example, when a schedule line is added, when a claim is allowed, or when the meeting is held — that recomputation is itself a mutation of the case: its `updated_at` is refreshed and its `version` increments by one.

Some operations cascade across more than one resource. Conducting the 341 meeting mutates both the meeting and its parent case. Allowing or disallowing a proof of claim mutates both the claim and the debt it points at. Granting relief from the stay mutates both the motion and the case's posture. Granting discharge mutates the case, can mark the active plan complete, and rewrites the allowed amounts of the case's unsecured debts. Each affected resource independently has its own `updated_at` refreshed and its own `version` incremented; the specific cascades are detailed in §3 alongside the workflows that trigger them.

### 2.6. Nested Resource Retrieval and Existence Ordering

Requests are validated in a fixed order. Authentication is checked first, then authorization, then the existence of resources. For any route that names a resource in its path, the system confirms that resource exists, validating path identifiers left to right; the first identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404) before any later identifier is examined. For create operations, foreign keys carried in the request body — the debtor, case, creditor, debt, plan, and trustee references — are then checked against existing rows; a body foreign key that resolves to nothing produces `ERR_FK_NOT_FOUND` (HTTP 404). Only after existence is settled does the system verify that required body fields are present and that each value falls within its declared type or enumeration domain, rejecting violations with `ERR_INVALID_REQUEST` (HTTP 422). State-transition preconditions and domain rules are evaluated after all of the foregoing.

### 2.7. Validation Precedence

When several checks could fire on a single request, they are evaluated in a strict order so that the resulting error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) precedes authorization (`ERR_UNAUTHORIZED`). Authorization precedes the existence of path resources (`ERR_NOT_FOUND`), which precedes the existence of body foreign keys (`ERR_FK_NOT_FOUND`), which precedes request well-formedness (`ERR_INVALID_REQUEST`). Only then is the resource's state checked against the requested transition (`ERR_INVALID_STATE`, HTTP 409). Domain-specific business rules — claim/creditor matching, relief-target classification, meeting conflicts, the means-test and discharge bars, the stay-termination guard, over-exemption, the chapter-13 gate, plan feasibility, plan overpayment, and the optimistic-concurrency check — are evaluated after the generic state check. The precise placement of each business rule is given in §3 next to the workflow it guards.

### 2.8. Monetary Precision

All monetary amounts in this system are expressed and stored as integer cents; field names that carry money end in `_cents`. Because every input is already an integer number of cents, the calculations are performed in integer arithmetic and no rounding is ever required. Aggregations are computed by exact integer addition and subtraction; the waterfall distribution in particular is a sequence of integer subtractions with no division and therefore no fractional remainder. Where a computed amount could otherwise go negative, the specification states explicitly that it is floored at zero rather than rounded.

### 2.9. The Automatic Stay Posture

The automatic stay is modeled as a derived field on the case, `stay_posture`, taking one of four values: `NONE`, `ACTIVE`, `LIFTED_PARTIAL`, or `TERMINATED`. While the case is still a draft it is `NONE`. The moment the petition is filed the posture becomes `ACTIVE`. Once any stay-relief motion on the case is granted, the posture moves to `LIFTED_PARTIAL`, reflecting that the stay has been lifted as to particular collateral while remaining in force otherwise. On discharge or dismissal the posture becomes `TERMINATED`.

This posture gates creditor collection activity. Filing a proof of claim and moving for relief from the stay are both creditor collection actions and may proceed only while the stay still permits them — that is, while `stay_posture` is `ACTIVE` or `LIFTED_PARTIAL`. Attempting either of these while the posture is `TERMINATED` is rejected with `ERR_STAY_TERMINATED` (HTTP 409).

### 2.10. Optimistic Concurrency on Plan Creation

Creating a Chapter 13 plan is the one operation in this system protected by optimistic concurrency control, because a fresh draft plan legitimately supersedes whatever plan was active on the case before it. A create-plan request must therefore carry `expected_case_version`, a non-optional field that holds the `version` of the parent case as the client last observed it. The server compares `expected_case_version` to the case's current `version`. If they match, the create proceeds; if another writer has advanced the case's `version` since the client read it, the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the client from superseding a plan against a case state it never saw. No other endpoint accepts or requires a version field; only plan creation participates in this check.

## 3. Business Logic & Workflows

### 3.1. Registries: Debtors, Creditors, and Trustees

Before a case can exist, the parties to it are registered. A `Debtor` is created with a `full_name` and an `email`; the email must be unique across all debtors. A debtor also carries `prior_discharge_within_8y`, a boolean defaulting to `false` that records whether the debtor already received a Chapter 7 discharge within the prior eight years — a fact that will later bar a fresh Chapter 7 discharge. A `Creditor` is registered with nothing more than a `name`, and a `Trustee` likewise with a `name`. Each of these registry records is independently addressable and may be fetched by its `id`.

### 3.2. Opening a Case and Establishing the Means Test

A case is opened in `DRAFT` by supplying the `debtor_id` of the filer, the `filed_chapter` the debtor petitions under — one of `CHAPTER_7` or `CHAPTER_13` — the two-letter uppercase `state_code` of the debtor's domicile, and the `household_size`, an integer of at least one. The state and household size together select the median-income figure and exemption set that apply to the filing. A freshly opened case begins with `status` equal to `DRAFT`, `stay_posture` equal to `NONE`, and `means_test_result` equal to `NOT_RUN`; its `petition_date` is null until the petition is filed.

The means test determines whether the debtor's income raises a presumption of abuse. The debtor submits it by providing the `case_id`, the current monthly income `cmi_monthly_cents` (the average gross monthly income over the six calendar months before the petition, in cents, at least zero), the allowed monthly living expenses `monthly_expenses_cents` (at least zero), and the applicable `median_annual_income_cents` selected from the state-and-household median table (at least zero). At most one means test exists per case; resubmitting replaces it. Submitting the test computes three things and mirrors the outcome up onto the case.

First, the system annualizes income: `annualized_cmi_cents` is the current monthly income multiplied by twelve. Second, it computes monthly disposable income, `disposable_monthly_cents`, as the current monthly income minus the allowed monthly expenses, but never below zero — if expenses meet or exceed income, disposable income is zero. Third, it determines the `result`. The first screen is the income screen against the state-and-household median: if the annualized income is **less than or equal to** the median annual income, the result is `PRESUMPTION_OK` and the debtor passes outright. Income exactly equal to the median passes on this screen; income even one cent above it falls through to the second screen. The second screen projects disposable income over the sixty-month commitment horizon — disposable monthly income multiplied by sixty — and compares it against an abuse floor of fifteen thousand dollars, i.e. 1,500,000 cents. If that sixty-month projection is **at least** the abuse floor, the result is `PRESUMPTION_ABUSE`; otherwise the result is `PRESUMPTION_OK`. The computed result is written both to the means test's own `result` and, denormalized, to the case's `means_test_result`; computing the means test is a mutation of the case and increments the case's `version`. The case's `means_test_result` and the means test's `result` share the same domain of `NOT_RUN`, `PRESUMPTION_OK`, and `PRESUMPTION_ABUSE`.

### 3.3. Building the Estate: Schedules A–J and Scheduled Debts

The debtor populates the estate through schedule line items. Each `Schedule` row names its `case_id`, a `schedule_letter` drawn from the set `A`, `B`, `C`, `D`, `E`, `F`, `G`, `H`, `I`, or `J`, and a free-text `description`. Letters `A` and `B` record real and personal property and carry an `asset_value_cents` (the fair-market value, at least zero, defaulting to zero); letter `C` records claimed exemptions and carries a `claimed_exempt_value_cents` (at least zero, defaulting to zero); the remaining letters record debts, contracts, codebtors, income (`I`), and expenses (`J`) and leave the value fields at their zero default. Adding any schedule line recomputes two derived case fields and bumps the case's `version`.

The two derived case fields are reconciled on every schedule mutation. `total_exempt_value_cents` is the sum of `claimed_exempt_value_cents` across all of the case's Schedule `C` rows. `nonexempt_estate_cents` is the gross scheduled asset value — the sum of `asset_value_cents` across all Schedule `A` and `B` rows — minus the total exempt value, floored at zero so an over-claim of exemptions never yields a negative estate.

There is a guard on Schedule `C`. When a Schedule `C` line is added, its `claimed_exempt_value_cents` must not exceed the case's gross scheduled asset value, that is, the current sum of `asset_value_cents` over the case's Schedule `A` and `B` rows. A claimed exemption above that gross is rejected with `ERR_EXEMPTION_EXCEEDS_ASSET` (HTTP 422).

Scheduled debts are recorded separately. A `Debt` names its `case_id`, the `creditor_id` it is owed to, a `debt_class` of `SECURED`, `PRIORITY`, or `UNSECURED` that drives later distribution priority, and a `scheduled_amount_cents` the debtor schedules as owed (at least one). Each debt also carries a derived `allowed_amount_cents`, the amount actually available for distribution; until a proof of claim is adjudicated against the debt, the allowed amount simply equals the scheduled amount.

### 3.4. Filing the Petition and the Rise of the Automatic Stay

The petition is the debtor's act that converts a draft into a live case, advancing `status` from `DRAFT` to `FILED`. It is permitted only when the case is still `DRAFT` (a case not in `DRAFT` is rejected with `ERR_INVALID_STATE`, HTTP 409), when the case has at least one Schedule row of letter `I` **and** at least one of letter `J` (income and expense schedules must both exist), and when a means test exists for the case whose `result` is no longer `NOT_RUN`; an attempt that fails either the Schedule `I`/`J` requirement or the completed-means-test requirement is likewise rejected with `ERR_INVALID_STATE` (HTTP 409). There is one chapter-specific gate: if the case was filed under `CHAPTER_7`, the case's `means_test_result` must be `PRESUMPTION_OK` — a presumption of abuse bars a Chapter 7 petition, and the attempt is rejected with `ERR_MEANS_TEST_ABUSE` (HTTP 409).

When the petition succeeds, the case's `status` becomes `FILED`, its `petition_date` is set to the filing instant in UTC (this date anchors the means-test six-month lookback), its `stay_posture` becomes `ACTIVE` as the automatic stay arises, and its `version` increments. From this point the stay gates all creditor collection activity as described in §2.9.

### 3.5. Scheduling and Holding the 341 Creditors' Meeting

Every filed case proceeds to a 341 creditors' meeting, of which there is at most one per case. A trustee schedules it by supplying the `case_id`, the `trustee_id` of the trustee who will chair it, a `room_code` for the hearing room, and the slot's `scheduled_start` and `scheduled_end` in UTC. The start is inclusive and the end is exclusive, and the end must be strictly after the start (a non-positive interval is a well-formedness failure rejected with `ERR_INVALID_REQUEST`, HTTP 422). The meeting is created with `status` of `SCHEDULED`, and scheduling requires that the case already be `FILED` — checked after well-formedness and before the conflict checks below, and rejected with `ERR_INVALID_STATE` (HTTP 409) when the case is in any other status.

Two independent conflict checks guard the schedule, and both must pass. The first is the **trustee** check, which uses half-open interval semantics. The proposed slot, treated as the interval from its start up to but not including its end, must not overlap any other `SCHEDULED` meeting assigned to the same `trustee_id`. Two such meetings conflict precisely when the new start is before the existing end and the existing start is before the new end; under these strict comparisons, two back-to-back meetings that merely share an endpoint (one ending exactly when the next begins) do **not** conflict. A trustee overlap is rejected with `ERR_TRUSTEE_DOUBLE_BOOKED` (HTTP 409).

The second is the **room** check, which is deliberately stricter because a room needs a cleanup gap between meetings. For any other `SCHEDULED` meeting sharing the same `room_code`, the room is treated as busy not just for that meeting's interval but for a window padded by a thirty-minute cleanup buffer on each side — from thirty minutes before its start to thirty minutes after its end. The new meeting's raw interval must not intersect that padded window; concretely, a conflict exists when the new start is before the padded end and the padded start is before the new end. Because of the buffer, mere adjacency is not enough in a room: there must be a gap of at least thirty minutes between consecutive meetings in the same room, so the back-to-back arrangement that passes the trustee check fails here. A room conflict is rejected with `ERR_ROOM_BUFFER_CONFLICT` (HTTP 409).

Only the assigned trustee may conduct the meeting. Holding the meeting requires that the meeting still be `SCHEDULED`, that the case be `FILED`, and that the acting trustee's `X-User-ID` equal the meeting's `trustee_id`; these are checked in that order, so a meeting that is not `SCHEDULED` or whose case is not `FILED` yields `ERR_INVALID_STATE` (HTTP 409), and a request by a trustee other than the assigned one is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Conducting it advances the meeting's `status` from `SCHEDULED` to `HELD` and, as a cross-entity cascade, bubbles the parent case from `FILED` to `MEETING_HELD`; both the meeting's `version` and the case's `version` increment.

### 3.6. Proofs of Claim and the Ledger Sync

After the meeting has been held, creditors' claims can be adjudicated. A creditor files a proof of claim by naming the `case_id`, the `debt_id` of the scheduled debt the claim corresponds to, its own `filed_by_creditor_id`, and the `claimed_amount_cents` it asserts is owed (at least one). The claim is created with `status` of `FILED`. Filing a claim is a creditor collection action and is therefore blocked when the stay is `TERMINATED`, as described in §2.9. Moreover, a creditor may only file against its own scheduled debts: the `filed_by_creditor_id` must equal the `creditor_id` recorded on the linked debt, and a mismatch is rejected with `ERR_CLAIM_CREDITOR_MISMATCH` (HTTP 409). These two guards are evaluated in the order written here: the stay-termination guard is checked before the creditor-mismatch guard, so on a request where both would fire — the stay is `TERMINATED` and the creditor does not match the debt — the result is `ERR_STAY_TERMINATED`.

The trustee adjudicates each filed claim, and claims may be adjudicated only while the case is `MEETING_HELD` or `CONFIRMED` — never before the 341 meeting. A claim not in `FILED` status, or a case in any other status, is rejected with `ERR_INVALID_STATE` (HTTP 409); the claim's own status is checked before the case's. Allowing a claim advances it from `FILED` to `ALLOWED`, sets the claim's `allowed_amount_cents` to its `claimed_amount_cents`, and synchronizes that allowed amount onto the linked debt by writing it into the debt's `allowed_amount_cents`; the claim's `version` increments. Disallowing a claim instead advances it from `FILED` to `DISALLOWED`, sets the claim's `allowed_amount_cents` to zero, and writes zero into the linked debt's `allowed_amount_cents`; again the claim's `version` increments. These two adjudications are mirror operations and receive equal treatment: allowance copies the claimed amount through to the debt, disallowance zeros it out, and in both cases the debt's allowed amount is what later feeds the Chapter 13 distribution.

### 3.7. The Chapter 13 Plan and Its Revision Cycle

A reorganization plan exists only for cases filed under `CHAPTER_13`; every plan operation — creating, filing, or confirming — first requires that the case's `filed_chapter` be `CHAPTER_13`, and an attempt on a Chapter 7 case is rejected with `ERR_NOT_CHAPTER_13` (HTTP 409). A debtor proposes a plan by supplying the `case_id`, a proposed `monthly_payment_cents` (at least one), a `plan_duration_months` commitment period that must be at least thirty-six and at most sixty months, and the `expected_case_version` (a required integer) for the optimistic-concurrency check described in §2.10. On create the chapter gate is evaluated before the optimistic-concurrency check, so on a Chapter 7 case the result is `ERR_NOT_CHAPTER_13` even when `expected_case_version` is also stale. On creation the plan begins in `DRAFT` with `is_active` true; its `total_committed_cents` is computed as the monthly payment multiplied by the duration in months, and its `paid_to_date_cents` begins at zero. Because a new draft plan supersedes any prior plan, creating it flips the prior active plan's `is_active` to false and increments the case's `version`. The flag `is_active` is true only for the case's latest-by-`created_at` plan that has not been denied; when several plans coexist, the most recently created non-denied plan is the active one and earlier ones are not.

The plan moves through a revision cycle. The debtor files the plan, advancing it from `DRAFT` to `FILED`; this is permitted only while the plan is still `DRAFT`, is the active plan, belongs to a Chapter 13 case, and the case is `FILED` or `MEETING_HELD`. The chapter guard is evaluated first, so filing against a Chapter 7 case yields `ERR_NOT_CHAPTER_13` (HTTP 409); a plan that is not the active `DRAFT` plan, or a case not in `FILED` or `MEETING_HELD`, yields `ERR_INVALID_STATE` (HTTP 409). The trustee then either confirms or denies the filed plan. Confirmation advances the plan from `FILED` to `CONFIRMED` and is permitted only while the case is `MEETING_HELD` and the plan satisfies the feasibility test below; here too the chapter guard fires first (`ERR_NOT_CHAPTER_13`), then a plan not in `FILED` or a case not in `MEETING_HELD` yields `ERR_INVALID_STATE`, and only then is feasibility checked. The plan's `version` increments. Denial advances the plan from `FILED` to `DENIED` (a plan not in `FILED` yields `ERR_INVALID_STATE`), sets its `is_active` to false, and increments its `version`; a denied plan is superseded, and the debtor drafts a fresh plan to start the cycle again. Denial applies no chapter guard.

Plan feasibility protects priority creditors, whose debts are non-dischargeable in Chapter 13. Before a plan may be confirmed, its `total_committed_cents` must be **at least** the priority floor — the sum of `allowed_amount_cents` across all of the case's debts whose `debt_class` is `PRIORITY`, using the post-allowance allowed amounts. A plan committing exactly the priority floor is feasible; a plan one cent short is infeasible and confirmation is rejected with `ERR_PLAN_INFEASIBLE` (HTTP 409).

### 3.8. Funding the Plan: Monthly Trustee Payments

Once a plan is confirmed, the trustee records the debtor's monthly payments against it. A plan payment names the `plan_id` and the `amount_cents` received this month (at least one); the system stamps `applied_at` with the UTC instant the trustee recorded it. Recording a payment adds its amount to the plan's running `paid_to_date_cents` and increments the plan's `version`. A payment that would drive `paid_to_date_cents` above the plan's `total_committed_cents` is rejected with `ERR_PLAN_OVERPAYMENT` (HTTP 422): the committed fund cannot be overpaid.

The distribution of the funded amount across creditors is available as a computed read keyed by the plan. It distributes the plan's current `paid_to_date_cents` across the case's debts in strict priority order, returning the plan's `plan_id`, its `paid_to_date_cents`, a `distribution` mapping whose keys are participating debt `id`s and whose values are the integer cents allocated to each, and any `surplus_cents` left over. This computed read returns its four fields directly in the response `data` and is not itself a persisted resource, so it carries no `id`, `created_at`, `updated_at`, or `version`. Only debts with a positive allowed amount participate. The classes are filled in the order `PRIORITY` first, then `SECURED`, then `UNSECURED`; within a single class, debts are taken in ascending `created_at`, with ascending `id` only as a last-resort tie-break. Allocation is fill-in-full, not pro-rata: walking the ordered debts, each debt receives the smaller of the remaining fund and its own `allowed_amount_cents`, that amount is subtracted from the remaining fund, and the walk continues. A fund that runs dry mid-class therefore pays the earlier-created debts in that class fully and leaves later ones at zero. Whatever remains after every debt is paid is the surplus returned to the debtor.

### 3.9. Relief from the Automatic Stay

While the stay is in force, a creditor may move to have it lifted as to specific collateral. A stay-relief motion names the `case_id`, the `movant_creditor_id` seeking relief, and the `target_debt_id` it wishes to act on. Filing the motion is a creditor collection action and is blocked when the stay is `TERMINATED` per §2.9. The targeted debt must be secured: its `debt_class` must be `SECURED`, and a motion against a non-secured debt is rejected with `ERR_RELIEF_TARGET_NOT_SECURED` (HTTP 409). The motion is created with `status` of `PENDING`.

The trustee rules on the motion. Granting it requires, in this order, that the motion still be `PENDING` (otherwise `ERR_INVALID_STATE`, HTTP 409), that the case's `stay_posture` be `ACTIVE` or `LIFTED_PARTIAL` (the stay must still be in force to be lifted; otherwise `ERR_INVALID_STATE`, HTTP 409), and that the target debt indeed be `SECURED` (otherwise `ERR_RELIEF_TARGET_NOT_SECURED`, HTTP 409). Granting advances the motion from `PENDING` to `GRANTED` and, as a cascade, moves the case's `stay_posture` to `LIFTED_PARTIAL`, partially lifting the stay as to the named collateral and incrementing the case's `version`. Denying the motion advances it from `PENDING` to `DENIED` (a motion not in `PENDING` is rejected with `ERR_INVALID_STATE`, HTTP 409) and increments the motion's own `version`; denial has no effect on the case posture.

### 3.10. Confirmation, Discharge, and Dismissal

After the meeting has been held, the case diverges by chapter. For a `CHAPTER_13` case, the trustee confirms the case, advancing its `status` from `MEETING_HELD` to `CONFIRMED`; this requires, checked in this order, that the case be `MEETING_HELD` (otherwise `ERR_INVALID_STATE`, HTTP 409), that it be a Chapter 13 case (otherwise `ERR_NOT_CHAPTER_13`, HTTP 409), and that it have a plan in `CONFIRMED` status (otherwise `ERR_INVALID_STATE`, HTTP 409). The case's `version` increments. A Chapter 7 case skips confirmation entirely and proceeds straight from `MEETING_HELD` to discharge.

Discharge is the trustee's grant of relief. On the Chapter 7 path it advances the case from `MEETING_HELD` to `DISCHARGED`; it requires that the case be `MEETING_HELD` (otherwise `ERR_INVALID_STATE`, HTTP 409), have a `means_test_result` of `PRESUMPTION_OK` (otherwise `ERR_INVALID_STATE`, HTTP 409 — not `ERR_MEANS_TEST_ABUSE`, which guards only the petition), and that the debtor's `prior_discharge_within_8y` be false — a prior discharge within eight years bars a new one and is rejected with `ERR_PRIOR_DISCHARGE_BAR` (HTTP 409); these are evaluated in that order, with the chapter selecting the path before any of them. On the Chapter 13 path discharge advances the case from `CONFIRMED` to `DISCHARGED` and requires that the case be `CONFIRMED` and that its active plan have been fully funded — `paid_to_date_cents` must be at least `total_committed_cents`; a wrong state, a missing active plan, or an under-funded plan is rejected with `ERR_INVALID_STATE` (HTTP 409). The chapter is read directly from the case's `filed_chapter` to choose between these two paths rather than checked as a separate guard. On the Chapter 13 path the active plan is additionally marked `COMPLETED`.

Whichever path is taken, discharge sets the case's `status` to `DISCHARGED` and its `stay_posture` to `TERMINATED`, reduces the `allowed_amount_cents` of every debt of class `UNSECURED` to zero (those debts are discharged) while leaving `SECURED` and `PRIORITY` debts intact, and increments the case's `version`. As part of the same settlement the estate's exempt and nonexempt split is reconciled: `total_exempt_value_cents` is recomputed as the sum of `claimed_exempt_value_cents` over the case's Schedule `C` rows, the gross asset value is the sum of `asset_value_cents` over the case's Schedule `A` and `B` rows, and `nonexempt_estate_cents` is set to that gross minus the total exempt value, floored at zero so an over-claim never produces a negative estate.

Dismissal is the alternative terminal outcome and may be ordered by the trustee while the case is `FILED`, `MEETING_HELD`, or `CONFIRMED`; a dismissal attempted from any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Dismissal sets the case's `status` to `DISMISSED`, sets its `stay_posture` to `TERMINATED`, moots the case by setting every `PENDING` stay-relief motion on it to `DENIED`, and increments the case's `version`. Both `DISCHARGED` and `DISMISSED` are terminal case states.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state transition and the recording of cascaded effects — return `200 OK`. Read operations return `200 OK`. The request body, response body, and side effects of each operation are described in the §3 narratives above; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/debtors` | Register a debtor | BankruptcyAdmin, Debtor |
| GET | `/debtors/{id}` | Fetch a debtor | BankruptcyAdmin, Debtor, Trustee |
| POST | `/creditors` | Register a creditor | BankruptcyAdmin, Creditor |
| GET | `/creditors/{id}` | Fetch a creditor | BankruptcyAdmin, Creditor, Trustee |
| POST | `/trustees` | Register a trustee | BankruptcyAdmin, Trustee |
| GET | `/trustees/{id}` | Fetch a trustee | BankruptcyAdmin, Trustee |
| POST | `/cases` | Open a bankruptcy case in DRAFT | BankruptcyAdmin, Debtor |
| GET | `/cases/{id}` | Fetch a case with all computed fields | BankruptcyAdmin, Debtor, Trustee, Creditor |
| GET | `/cases` | List cases; filter by debtor_id and status | BankruptcyAdmin, Trustee |
| POST | `/cases/{id}/petition` | File the petition; automatic stay arises | Debtor |
| POST | `/cases/{id}/confirm` | Confirm the case for Chapter 13 | Trustee |
| POST | `/cases/{id}/discharge` | Grant discharge | Trustee |
| POST | `/cases/{id}/dismiss` | Dismiss the case | Trustee |
| POST | `/means-tests` | Submit/compute the means test for a case | Debtor |
| GET | `/means-tests/{id}` | Fetch a means-test row | BankruptcyAdmin, Debtor, Trustee |
| GET | `/means-tests` | List means tests; filter by case_id | BankruptcyAdmin, Debtor, Trustee |
| POST | `/meetings` | Schedule the 341 creditors' meeting | Trustee |
| GET | `/meetings/{id}` | Fetch a 341 meeting | BankruptcyAdmin, Debtor, Trustee, Creditor |
| GET | `/meetings` | List meetings; filter by case_id, trustee_id, status | BankruptcyAdmin, Debtor, Trustee, Creditor |
| POST | `/meetings/{id}/hold` | Trustee conducts the scheduled meeting | Trustee |
| POST | `/schedules` | Add a Schedule A–J line item to a case | Debtor |
| GET | `/schedules/{id}` | Fetch a schedule row | BankruptcyAdmin, Debtor, Trustee, Creditor |
| GET | `/schedules` | List schedule rows; filter by case_id, schedule_letter | BankruptcyAdmin, Debtor, Trustee, Creditor |
| POST | `/debts` | Schedule a debt under a case | Debtor |
| GET | `/debts/{id}` | Fetch a debt | BankruptcyAdmin, Debtor, Trustee, Creditor |
| GET | `/debts` | List debts; filter by case_id, creditor_id, debt_class | BankruptcyAdmin, Debtor, Trustee, Creditor |
| POST | `/claims` | Creditor files a proof of claim against a debt | Creditor |
| GET | `/claims/{id}` | Fetch a claim | BankruptcyAdmin, Debtor, Trustee, Creditor |
| GET | `/claims` | List claims; filter by case_id, debt_id, filed_by_creditor_id, status | BankruptcyAdmin, Debtor, Trustee, Creditor |
| POST | `/claims/{id}/allow` | Trustee allows a filed claim | Trustee |
| POST | `/claims/{id}/disallow` | Trustee disallows a filed claim | Trustee |
| POST | `/plans` | Create a Chapter 13 reorganization plan | Debtor |
| GET | `/plans/{id}` | Fetch a plan | BankruptcyAdmin, Debtor, Trustee |
| GET | `/plans` | List plans; filter by case_id, status | BankruptcyAdmin, Debtor, Trustee |
| POST | `/plans/{id}/file-plan` | Debtor files the plan | Debtor |
| POST | `/plans/{id}/confirm-plan` | Trustee confirms a filed plan after feasibility | Trustee |
| POST | `/plans/{id}/deny-plan` | Trustee denies a filed plan | Trustee |
| GET | `/plans/{id}/distribution` | Computed waterfall distribution of the funded amount | BankruptcyAdmin, Debtor, Trustee |
| POST | `/plan-payments` | Record a monthly trustee payment against a plan | Trustee |
| GET | `/plan-payments/{id}` | Fetch a plan payment | BankruptcyAdmin, Debtor, Trustee |
| GET | `/plan-payments` | List plan payments; filter by plan_id | BankruptcyAdmin, Debtor, Trustee |
| POST | `/stay-relief-motions` | Creditor moves for relief from the automatic stay | Creditor |
| GET | `/stay-relief-motions/{id}` | Fetch a stay relief motion | BankruptcyAdmin, Debtor, Trustee, Creditor |
| GET | `/stay-relief-motions` | List relief motions; filter by case_id, movant_creditor_id, target_debt_id, status | BankruptcyAdmin, Debtor, Trustee, Creditor |
| POST | `/stay-relief-motions/{id}/grant` | Trustee grants relief; stay partially lifts | Trustee |
| POST | `/stay-relief-motions/{id}/deny` | Trustee denies relief | Trustee |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLAIM_CREDITOR_MISMATCH` | 409 |
| `ERR_RELIEF_TARGET_NOT_SECURED` | 409 |
| `ERR_TRUSTEE_DOUBLE_BOOKED` | 409 |
| `ERR_ROOM_BUFFER_CONFLICT` | 409 |
| `ERR_MEANS_TEST_ABUSE` | 409 |
| `ERR_PRIOR_DISCHARGE_BAR` | 409 |
| `ERR_STAY_TERMINATED` | 409 |
| `ERR_EXEMPTION_EXCEEDS_ASSET` | 422 |
| `ERR_NOT_CHAPTER_13` | 409 |
| `ERR_PLAN_INFEASIBLE` | 409 |
| `ERR_PLAN_OVERPAYMENT` | 422 |
| `ERR_STALE_CASE_VERSION` | 412 |
