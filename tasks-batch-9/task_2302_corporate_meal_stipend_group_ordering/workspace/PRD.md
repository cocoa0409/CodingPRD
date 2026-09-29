# Corporate Meal Stipend API — Product Requirements Document

## 1. Introduction

Employers who fund meals for their staff sit on an uncomfortable seam. On one side is a payroll and finance organisation that needs every cent of employer money to be traceable, forecastable, and correctly reported as a taxable benefit. On the other side is an employee who simply wants lunch, occasionally spends more than the company will cover, and expects the difference to land on a personal card without ceremony. Between them sits a delivery marketplace with its own fees, radius limits, and restaurant capacity. The Corporate Meal Stipend API is the system of record that holds that seam together.

The service governs the whole arc of a corporate meal benefit: a program is stood up for an employer, employees are sorted into groups, each group is governed by a versioned budget rule that fixes a per-meal cap and the days and hours on which the benefit may be used, and each employee receives a monthly budget period funded by that rule plus whatever unused money the previous month was permitted to carry forward. Employees draft orders, optionally band together into coordinated group orders delivered to a shared dock, place them against their remaining budget, and receive food. Every placement splits into an employer share and a personal-card share; every delivery accrues imputed income into a monthly payroll bucket; every missing item or quality complaint routes a credit back to whichever party actually paid for it.

Because the same money is simultaneously an employer budget line, a personal-card charge, a platform fee, and a taxable benefit, this specification treats reconciliation as the primary correctness requirement. Four independent ledgers — the benefit period's budget partition, the order's charge and refund totals, the immutable refund ledger, and the employee's imputed-income accrual — must agree after every single money movement, including refunds, voids, period closes, and rollovers. Amounts are therefore expressed in whole cents throughout, every rounding step is pinned to a named stage, and every state transition that moves money is described together with the cascades it triggers.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold for the entire API: authentication, response shape, pagination, identity and versioning semantics, the temporal model, monetary precision, the reconciliation invariants, optimistic concurrency, and the strict order in which request validations are evaluated.

All resources are mounted as flat peer collections at the API root; there is no global path prefix.

### 2.1. User and Role-Based Access Control

Every request to every endpoint must carry two headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which that principal is acting. If either header is absent, or if `X-User-Role` does not name one of the five roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before the request body is even parsed. Once identity is established, the declared role is checked against the set of roles the target endpoint admits; a caller whose role is not admitted receives `ERR_UNAUTHORIZED` (HTTP 403), and this happens even when the request body is malformed, so an unauthorised caller never learns whether their payload would have been accepted.

The five roles are `PlatformAdmin`, `ProgramAdmin`, `BenefitsController`, `Employee`, and `Restaurant`. Their responsibilities are separated deliberately:

- A `PlatformAdmin` is the marketplace operator. It creates and edits meal programs, registers restaurants, and suspends or reinstates them. It never touches employer money decisions.
- A `ProgramAdmin` is the employer's benefits-operations staff. It structures the program — employee groups and delivery docks — enrols and deactivates employees, opens benefit periods, and closes them.
- A `BenefitsController` is the employer's financial controller. It authors and activates budget rules, resolves and settles credit claims, and generates and acknowledges expense and payroll exports.
- An `Employee` drafts, places, and cancels their own orders, organises group orders, and raises credit claims.
- A `Restaurant` confirms and delivers orders addressed to itself and sees nothing else.

Identity semantics differ by role, and they determine how ownership is enforced. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's employee-referencing field to `X-User-ID` — an order's `employee_id`, a group order's `organizer_employee_id`, a benefit period's `employee_id`, and, for a credit claim, the `employee_id` of the order the claim addresses. When `X-User-Role` is `Restaurant`, `X-User-ID` is the `id` of the acting `Restaurant`; a confirm or deliver request is admitted only when the target order's `restaurant_id` equals `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `ProgramAdmin`, or `BenefitsController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — it is stored as `drafted_by_user_id` on a `BudgetRule` when the rule is drafted, and as `resolved_by_user_id` on a `CreditClaim` when the claim is resolved — but it is never compared to any entity's `id`.

A caller whose role is correct but whose target row belongs to somebody else is a different failure from an unauthorised role, and it carries a different code: `ERR_FORBIDDEN_RESOURCE` (HTTP 403). This ownership scoping guards twelve operations: drafting an order, placing an order, cancelling an order, confirming an order, delivering an order, locking a group order, reopening a group order, submitting a group order, cancelling a group order, creating a credit claim, reading a single order, and reading a single employee.

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

List endpoints accept two optional query parameters. `limit` caps the number of items returned; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. A `limit` below 1 or above 100 is a request-shape violation and yields `ERR_INVALID_REQUEST`. `offset` is the number of matching items to skip before the page begins; it defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of items matching the filters before pagination is applied and `has_more` indicates whether items remain beyond the current page. The only endpoint with a different ordering contract is the eligible-restaurant search described in §3.4, which ranks by distance and then by name.

### 2.4. Resource Identity, Timestamps and Versioning

Every resource in the system carries a server-minted `id`: a UUID string with no type prefix and no client-supplied component. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first persisted.

Most resources — meal programs, employee groups, budget rules, employees, benefit periods, restaurants, delivery locations, group orders, orders, credit claims, imputed income records, and expense exports — additionally carry `updated_at` and `version`. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the row, and `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation, including mutations the server performs on its own initiative as a cascade from some other operation. A refreshed derived rollup is a mutation: when a delivery moves employer cents out of a benefit period's reservation and into its spend, that period's `updated_at` and `version` both move even though no client addressed the period directly.

The single exception is `RefundLedgerEntry`, which is append-only and immutable. A refund ledger entry carries only `id` and `created_at`; it has no `updated_at` and no `version`, and once written it is never altered or deleted. Its `created_at` is the logical instant at which the money moved and is the chronological ordering key of the ledger.

### 2.5. The Logical Clock

Every temporal rule in this specification — weekday and window eligibility, group-order cutoffs, budget-rule effectiveness, tax-month bucketing, and forecasting — reads a single server-side logical UTC clock rather than wall-clock time. Before the clock is ever set, its value is `2026-08-01T00:00:00Z`. An administrative capability, available to `PlatformAdmin` and `ProgramAdmin`, sets the clock to a supplied `now` instant and echoes that instant back; setting the clock mutates no entity, and subsequent temporal evaluations simply read the new value.

All datetime values accepted and returned by the API are ISO 8601 UTC instants. Weekday numbering follows ISO-8601: 1 is Monday through 7 is Sunday. Minute-of-day is counted from UTC midnight, so 0 is midnight and 720 is noon.

### 2.6. Money, Distance and Rounding Discipline

Every monetary quantity in this system is an integer number of cents. There are no decimal currency fields, and no monetary value is ever rounded to two decimal places, because none is ever fractional in the first place. Where a rate is applied to a cents amount, the product is rounded to a whole cent using round-half-up — a residue of exactly half a cent rounds away from zero, upward.

What makes the money pipeline exacting is not the rounding method but *where* the rounding happens. Five stages move value through an order, and each stage has its own pinned rounding contract: line tax is rounded once per line before any summation; the platform service fee is rounded once when the raw rate is applied and once again when the volume discount is applied; the employer/employee split performs no rounding at all, only selection of the smallest of several ceilings; the program administration fee is rounded once; and refund routing rounds once, on the employee side only. Re-deriving any of these in a different order produces different cents, so the order stated in §3.5 and §3.8 is normative rather than illustrative.

Distances are the one non-monetary quantity with a rounding rule. The straight-line planar distance between a restaurant and a delivery dock, in kilometres, is rounded half-up to exactly three decimal places *before* it is compared against any radius limit. A restaurant sitting at a rounded distance exactly equal to the applicable limit is in range; the comparison is inclusive.

### 2.7. The Budget Partition and the Reconciliation Invariants

A `BenefitPeriod` is not a single balance; it is a partition of one allocation into five named buckets. `allocated_cents` is the total money granted to the period. `reserved_cents` holds employer cents committed to orders that have been placed or confirmed but not yet delivered. `spent_cents` holds employer cents captured by delivered orders, net of any employer credits later issued against them. `forfeited_cents` holds cents extinguished at final close. `rollover_out_cents` holds cents handed to a successor period at final close. `available_cents` is what remains: the allocation minus the reserved, spent, forfeited, and rolled-out buckets. Consequently `allocated_cents` always equals the sum of `available_cents`, `reserved_cents`, `spent_cents`, `forfeited_cents`, and `rollover_out_cents`, and that identity must hold after every placement, delivery, cancellation, settlement, and close.

Two further invariants are compensating rather than partitioning. Cash conservation requires that, for any order, `net_charged_cents` equals `gross_total_cents` less `employer_refunded_cents` less `employee_refunded_cents`, and that the sum of all `amount_cents` on the order's refund ledger entries equals `employer_refunded_cents` plus `employee_refunded_cents`. Imputed-income conservation requires that an employee's `ytd_imputed_cents` always equals the sum of `taxable_cents` across all of that employee's `ImputedIncomeRecord` rows, and that each record's `taxable_cents` equals the sum of `taxable_cents` across the delivered orders in its month. Because these are re-derived rather than accumulated, a refund that reduces an employer share must walk back through the imputed record and the employee total in the same transaction that writes the ledger.

Program-level rollups on `MealProgram` are likewise re-derived, never incremented blindly. `program_spent_cents` is the sum of `employer_net_cents` over all non-voided orders in the program. `program_reserved_cents` is the sum of `reserved_cents` over every benefit period in the program whose status is `OPEN` or `GRACE`. `mtd_employer_captured_cents` is the employer-covered cents captured by deliveries falling in the logical clock's current calendar month, and it is the tier input to the administration fee. Every money move recomputes the rollups it touches.

### 2.8. Optimistic Concurrency Control

Three write operations require the client to prove it has read the current state of a parent record before it is allowed to change money or structure. Each takes a mandatory version field — not optional, not defaulted — and each rejects a mismatch with its own code at HTTP 412.

A `POST /orders/{id}/place` request must carry `expected_benefit_period_version` holding the client's last observed `version` of the order's `BenefitPeriod`. If that value does not equal the period's current `version` at evaluation time, the placement is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412). A successful placement increments the period's `version` by 1, so a client that read `available_cents` earlier and did not re-read it is refused rather than allowed to reserve budget against a balance that has since moved.

A `POST /budget-rules/{id}/activate` request must carry `expected_employee_group_version` holding the client's last observed `version` of the owning `EmployeeGroup`. A mismatch is rejected with `ERR_STALE_EMPLOYEE_GROUP_VERSION` (HTTP 412). A successful activation increments the group's `version` by 1, which is what preserves the at-most-one-active-rule-per-group invariant: a second activation issued against the pre-activation version is refused.

A `POST /credit-claims/{id}/resolve` request must carry `expected_order_version` holding the client's last observed `version` of the `Order` the claim addresses. A mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). Delivery, cancellation, claim resolution, and claim settlement each increment the order's `version` by 1, so a routing split computed from a superseded employer/employee ratio can never be committed.

No other endpoint accepts a version field. In particular, confirm, deliver, cancel, lock, reopen, submit, settle, close, deactivate, and acknowledge take no version input at all.

### 2.9. Segregation of Duties

Two workflows are deliberately two-person operations. Drafting a budget rule records the drafter's `X-User-ID` as `drafted_by_user_id`; activating that rule requires a caller whose `X-User-ID` differs from the recorded drafter. Resolving a credit claim records the resolver's `X-User-ID` as `resolved_by_user_id`; settling that claim requires a caller whose `X-User-ID` differs from the recorded resolver. In both cases a same-user attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409), and that check runs before the request body is validated so a four-eyes violation cannot be masked behind a payload error.

### 2.10. Request Evaluation Order

Validations are evaluated strictly in the priority order below. The first rule that is violated determines the response, and nothing after it runs. This ordering is observable and is part of the contract: a request that violates several rules at once reports only the earliest.

1. Headers present and `X-User-Role` names a declared role — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. The caller's role appears in the endpoint's admitted role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. Ownership scoping for `Employee` and `Restaurant` callers — otherwise `ERR_FORBIDDEN_RESOURCE` (403). Applies to the twelve operations enumerated in §2.1.
4. Segregation of duties — otherwise `ERR_SEGREGATION_OF_DUTIES` (409). Applies to budget-rule activation and credit-claim settlement.
5. Request shape: required fields present, declared types, enum domains, numeric ranges, array cardinalities, and pagination bounds — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint. This covers a missing required field, an unknown enum member, negative cents, an empty `lines` array, a `lines` array longer than 20 elements, and a `limit` outside 1 through 100.
6. The entity addressed by an `{id}` path segment exists — otherwise the entity-specific 404: `ERR_MEAL_PROGRAM_NOT_FOUND`, `ERR_EMPLOYEE_GROUP_NOT_FOUND`, `ERR_BUDGET_RULE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_BENEFIT_PERIOD_NOT_FOUND`, `ERR_RESTAURANT_NOT_FOUND`, `ERR_DELIVERY_LOCATION_NOT_FOUND`, `ERR_GROUP_ORDER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_CREDIT_CLAIM_NOT_FOUND`, or `ERR_EXPENSE_EXPORT_NOT_FOUND`. Applies to every endpoint carrying a path parameter.
7. Every foreign key supplied in the request body resolves to an existing row, checked in the declaration order of the endpoint's input list — otherwise the same entity-specific 404 codes. Applies to order drafting, group-order creation, employee enrolment, benefit-period opening, credit-claim creation, employee-group creation, delivery-location creation, expense-export generation, budget-rule drafting, and the eligible-restaurant search.
8. The addressed entity is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint, and covers repeat invocation such as placing an already-placed order, terminal-state lockdown, and undeclared jumps such as delivering before confirming.
9. The order's benefit period is `OPEN` — otherwise `ERR_PERIOD_NOT_OPEN` (409). Applies to placement.
10. The ordering employee is `ACTIVE` — otherwise `ERR_EMPLOYEE_INACTIVE` (409). Applies to placement and group-order creation.
11. The restaurant is `ELIGIBLE` — otherwise `ERR_RESTAURANT_NOT_ELIGIBLE` (409). Applies to placement, order confirmation, and group-order submission.
12. The referenced group order is `COLLECTING` — otherwise `ERR_GROUP_ORDER_NOT_COLLECTING` (409). Applies to order drafting and placement.
13. The supplied expected-version field matches the parent's current `version` — otherwise `ERR_STALE_PERIOD_VERSION`, `ERR_STALE_EMPLOYEE_GROUP_VERSION`, or `ERR_STALE_ORDER_VERSION` (412). Applies to placement, budget-rule activation, and claim resolution. Concurrency runs after the cheap state gates but before any money is computed or moved.
14. The affected imputed-income bucket is neither `LOCKED` nor `EXPORTED` — otherwise `ERR_TAX_MONTH_LOCKED` (409). Applies to delivery, claim resolution, and claim settlement.
15. No order attached to the period is `PLACED` or `CONFIRMED` — otherwise `ERR_PERIOD_HAS_OPEN_ORDERS` (409). Applies to period close, and only when the requested `mode` is `FINAL`; `mode` `GRACE` is precisely the mechanism for draining those orders and is never blocked by this rule.
16. The employee has no `PLACED` or `CONFIRMED` order — otherwise `ERR_EMPLOYEE_HAS_OPEN_ORDERS` (409). Applies to employee deactivation.
17. The ISO weekday of `requested_delivery_at` is among the pinned rule's `eligible_weekdays` — otherwise `ERR_OUTSIDE_ELIGIBLE_WEEKDAY` (422). Applies to placement. Weekday eligibility precedes window eligibility, so a Saturday noon order reports the weekday, not the window.
18. The minute-of-day of `requested_delivery_at` lies in the half-open eligible window — otherwise `ERR_OUTSIDE_ELIGIBLE_WINDOW` (422). Applies to placement.
19. The logical clock is strictly before the group order's `cutoff_at` — otherwise `ERR_GROUP_CUTOFF_PASSED` (409). Applies to order drafting, placement, and group-order reopening.
20. No other submitted group order occupies the dock over the buffered closed interval — otherwise `ERR_DOCK_WINDOW_CONFLICT` (409). Applies to group-order submission.
21. Overlapping submitted group orders at the restaurant remain below its concurrency ceiling — otherwise `ERR_RESTAURANT_CAPACITY_EXCEEDED` (409). Applies to group-order submission.
22. `benefit_period_id` belongs to `employee_id` — otherwise `ERR_PERIOD_EMPLOYEE_MISMATCH` (422). Applies to order drafting.
23. Every referenced employee group, delivery location, employee, and benefit period belongs to the same meal program as the operation — otherwise `ERR_PROGRAM_SCOPE_MISMATCH` (422). Applies to order drafting, group-order creation, employee enrolment, expense-export generation, and the eligible-restaurant search.
24. A member order's `restaurant_id` and `delivery_location_id` equal the group order's — otherwise `ERR_GROUP_ORDER_MISMATCH` (422). Applies to order drafting.
25. The employee's group has exactly one budget rule in `ACTIVE` status — otherwise `ERR_NO_ACTIVE_BUDGET_RULE` (409). Applies to benefit-period opening.
26. `predecessor_period_id`, when supplied, names a `CLOSED` period of the same employee whose `period_month` is strictly earlier — otherwise `ERR_PREDECESSOR_NOT_CLOSED` (409). Applies to benefit-period opening.
27. `predecessor_period_id` is not already referenced by another benefit period — otherwise `ERR_PREDECESSOR_ALREADY_CONSUMED` (409). Applies to benefit-period opening.
28. `period_month` is unique per employee — otherwise `ERR_DUPLICATE_PERIOD_MONTH` (409). Applies to benefit-period opening.
29. An employee group's `name`, an employee's `email`, and a delivery location's `label` are each unique within their program, compared case-insensitively — otherwise `ERR_DUPLICATE_NAME` (409). Applies to employee-group creation, delivery-location creation, and employee enrolment.
30. The rounded distance from dock to restaurant is within the tighter of the two radius limits — otherwise `ERR_RESTAURANT_OUT_OF_RANGE` (422). Applies to placement and group-order creation.
31. The restaurant's `cuisine` is a member of the program's `eligible_cuisines` — otherwise `ERR_CUISINE_NOT_ELIGIBLE` (422). Applies to placement and group-order creation. This is independent of distance.
32. The employee's live order count for the requested UTC date is below the pinned `daily_meal_limit` — otherwise `ERR_DAILY_MEAL_LIMIT_EXCEEDED` (409). Applies to placement.
33. A member order's pre-fee base is within the group order's `per_person_limit_cents` — otherwise `ERR_PER_PERSON_LIMIT_EXCEEDED` (422). Applies to placement.
34. The group order's `reopen_count` is below the reopen ceiling — otherwise `ERR_REOPEN_LIMIT_EXCEEDED` (409). Applies to group-order reopening.
35. `line_index` is present and addresses an existing line when `claim_type` is `MISSING_ITEM`, and is absent when `claim_type` is `NEVER_DELIVERED` — otherwise `ERR_LINE_INDEX_INVALID` (422). Applies to credit-claim creation.
36. The claimed or approved amount does not exceed the order's remaining refundable amount, and for a `MISSING_ITEM` claim does not exceed the addressed line's base plus that line's rounded tax — otherwise `ERR_CLAIM_EXCEEDS_ORDER` (422). Applies to credit-claim creation and to claim resolution.
37. When the split would leave a positive personal-card amount, the pinned rule's `overage_policy` is `PERSONAL_CARD` — otherwise `ERR_OVERAGE_NOT_PERMITTED` (409). Applies to placement and group-order submission.
38. The period's `available_cents` is at least the smaller of the covered base and the per-meal cap — otherwise `ERR_PERIOD_BUDGET_EXCEEDED` (409). Applies to placement and group-order submission.
39. When the split would leave a positive personal-card amount, the employee has `personal_card_on_file` set to true — otherwise `ERR_PERSONAL_CARD_REQUIRED` (402). Applies to placement and group-order submission. This is the last gate: there must be an instrument to collect the employee remainder and any uncovered tip.

Note the interaction between ranks 37, 38, and 39. All three are evaluated *after* the split has been computed, in exactly that order, so a blocked-overage group whose period is also exhausted reports `ERR_OVERAGE_NOT_PERMITTED` rather than `ERR_PERIOD_BUDGET_EXCEEDED`.

### 2.11. Nested Path Resolution and Tenant Scoping

Several endpoints address a child collection through its parent, for example a program's employee groups, a program's delivery docks, a group's budget rules, or an employee's imputed-income records. Path identifiers are resolved strictly left to right, and the first identifier that fails to resolve determines the 404 that comes back. A request for the budget rules of a non-existent employee group returns `ERR_EMPLOYEE_GROUP_NOT_FOUND`; the server never proceeds to look for rules. The same precedence holds for creation: the parent must exist before any child-level validation runs.

Tenant isolation is enforced across the flat topology by explicit program-scope checks rather than by path nesting. Because orders, group orders, benefit periods, and employees are all peer resources at the root, a request that mixes rows from two different meal programs is a referential error, not a not-found: it yields `ERR_PROGRAM_SCOPE_MISMATCH`. Restaurants are the deliberate exception — they belong to the platform catalogue, not to any single program, and are shared across programs subject to the cuisine allow-list and radius tests.

### 2.12. Policy Pinning and Variant Selection

Three separate calculations in this system have two variants each, and the moment at which each variant is fixed is different. This is intentional: it means a program-level policy edit changes future behaviour without rewriting history.

The budget rule that governs an order is pinned onto the `BenefitPeriod` as `budget_rule_id` at the moment the period is opened, and is never re-read afterwards. If a controller activates a new rule for the group mid-month, already-open periods continue to price against the rule they pinned.

The taxable-benefit method is pinned onto the `ImputedIncomeRecord` as `method` at the moment that monthly record is first created — that is, by the first delivery in the month — copied from the program's `taxable_benefit_method` as it stands then. A later change to the program's `taxable_benefit_method` does not retroactively change any existing record's `method`.

The refund routing basis is chosen at claim resolution and stored as `routing_basis` on the `CreditClaim`; settlement simply executes the stored basis. The forecast basis, by contrast, is *not* pinned at all: the forecast endpoint reads the program's `forecast_basis` live on every call, so flipping the selector immediately changes the next forecast.

Editing a program's policy selectors mutates the program row — bumping its `version` by 1 and refreshing `updated_at` — and recomputes nothing. No historical order, imputed record, or export is re-derived.

## 3. Business Logic & Workflows

### 3.1. Program Foundations: Employer Setup, Groups and Delivery Docks

A `PlatformAdmin` begins by creating a meal program for an employer, supplying the `employer_name` under which the benefit is offered and a `billing_account_ref`, the opaque employer billing account reference that later appears on expense exports. The program also carries the policy selectors that govern its whole tenancy: `eligible_cuisines` is a required, non-empty array of distinct uppercase cuisine tags, and a restaurant whose cuisine is not in that allow-list is never eligible under this program, no matter how close it sits. `max_delivery_radius_km` is the program-wide radius ceiling in kilometres, measured from the delivery dock; it is optional, defaults to 8.0, and must be greater than 0 and at most 50.0. `taxable_benefit_method` selects the imputed-income variant and defaults to `DE_MINIMIS_EXCLUSION`, the alternative being `FULL_INCLUSION`. `rollover_policy` decides what happens to unused budget at close and defaults to `CAPPED_PCT`, with `NONE` and `FULL` as the alternatives. `rollover_cap_pct` is the fraction of the original allocation that may roll forward under `CAPPED_PCT`; it defaults to 0.25, must be at least 0 and at most 1, and is simply ignored when the policy is `NONE` or `FULL`. `forecast_basis` selects the forecasting variant and defaults to `COMMITMENT`, the alternative being `RUN_RATE`. At creation, the three program rollups `program_spent_cents`, `program_reserved_cents`, and `mtd_employer_captured_cents` all start at 0.

Under the program, a `ProgramAdmin` creates employee groups. Each group carries a `name` — the label the employer uses, such as Engineering — and `headcount_planned`, the planned headcount, which must be at least 1 and which becomes the multiplier used by commitment-basis forecasting. A group's `program_id` is established by the program under which it is created. A newly created group has `active_rule_count` of 0; that counter tracks how many of the group's budget rules are currently `ACTIVE` and is invariantly either 0 or 1.

The same administrator creates the delivery docks that receive food. A dock carries a human `label` such as HQ Lobby, its planar grid coordinates `grid_x_km` and `grid_y_km` in kilometres, and `dock_buffer_minutes`, the minutes of exclusive dock occupancy padded on after a group delivery window ends. The buffer is optional, defaults to 15, and must be at least 0 and at most 120. Its effect is described in §3.6: it is what turns dock occupancy into a closed interval and makes two back-to-back windows collide. Like a group's `name`, a dock's `label` must be unique within its program when compared without regard to case, and a collision is refused with `ERR_DUPLICATE_NAME`.

Restaurants live in the platform catalogue and are registered by a `PlatformAdmin` with a display `name`, a single uppercase `cuisine` tag, planar coordinates `grid_x_km` and `grid_y_km`, and `delivery_radius_km` — how far the restaurant is willing to travel, which must be greater than 0. `max_concurrent_group_deliveries` bounds how many submitted group orders may have overlapping delivery windows at that restaurant; it is optional, defaults to 1, and must be at least 1. A restaurant is created `ELIGIBLE` and a `PlatformAdmin` may cycle it between `ELIGIBLE` and `SUSPENDED` at will by writing the desired `status`. Suspension bumps the restaurant's `version` and takes it out of eligibility search and out of new placements immediately, but it does not disturb history: an order already `CONFIRMED` may still be delivered, and no delivered order is re-priced. Reinstatement makes the restaurant selectable again and likewise re-derives nothing.

### 3.2. Budget Rule Authorship, Four-Eyes Activation and Supersession

A `BenefitsController` drafts a budget rule against an employee group; the rule's `group_id` is taken from the group under which it is drafted. The draft fixes `effective_from`, the first UTC instant at which the rule may be pinned to a benefit period; `per_meal_cap_cents`, the maximum employer contribution to a single order's covered base, at least 1; `daily_meal_limit`, the maximum number of live orders one employee may hold on a single eligible UTC calendar day, at least 1 and at most 5; and `monthly_allocation_cents`, the employer budget granted to each employee in the group when a period opens, which may be 0 but not negative. Eligibility is fixed by `eligible_weekdays`, a non-empty array of distinct ISO weekday numbers drawn from 1 through 7, together with `eligible_window_start_minute` and `eligible_window_end_minute`, both expressed as minutes from UTC midnight. The start minute must be at least 0 and at most 1440; the end minute must be strictly greater than the start minute and at most 1440. The window is half-open: an order requested exactly at the start minute is admitted, and one requested exactly at the end minute is refused. A window from 660 to 900 therefore covers eleven in the morning through three in the afternoon, admitting 11:00 and rejecting 15:00.

Two optional policy switches complete the draft. `overage_policy` decides what happens when an order's covered base outruns the per-meal cap: it defaults to `PERSONAL_CARD`, meaning the remainder is collected from the employee, and may instead be `BLOCK`, meaning such an order is simply refused. `tip_coverage_policy` decides whether a tip is admitted into the employer-eligible base at all: it defaults to `EMPLOYEE_PAYS_TIP` and may instead be `EMPLOYER_COVERS_TIP`. Drafting records the drafter's identifier as `drafted_by_user_id` and creates the rule in `DRAFT`.

Activation is where the four-eyes control bites. A different `BenefitsController` — one whose acting identifier differs from `drafted_by_user_id` — activates the draft, supplying `expected_employee_group_version`. The rule must be in `DRAFT`, or the request is `ERR_INVALID_STATE`; the same-person attempt is `ERR_SEGREGATION_OF_DUTIES`; and a rule whose `effective_from` is strictly after the current logical clock is not yet activatable and is refused with `ERR_RULE_NOT_EFFECTIVE`. A rule whose `effective_from` falls exactly on the current clock instant *is* activatable. On success the rule moves `DRAFT → ACTIVE` and receives `rule_sequence`, a one-based activation ordinal within the group: the first rule ever activated in a group takes 1, the next takes 2, and so on, with numbers never reused even after supersession. The group's previously `ACTIVE` rule, if there is one, moves `ACTIVE → SUPERSEDED` in the same operation. The group's `version` increments by 1 and its `active_rule_count` is recomputed, which is how the invariant of at most one active rule per group is held: a competing activation issued against the pre-activation group version is refused with `ERR_STALE_EMPLOYEE_GROUP_VERSION`.

Supersession is forward-looking only. Benefit periods that already pinned the outgoing rule keep their pinned `budget_rule_id` and continue to price against it; nothing about an open period changes when the rule behind it is superseded. `SUPERSEDED` is terminal — a superseded rule can never be reactivated.

### 3.3. Enrolment, Benefit Periods and Rollover Draw-In

A `ProgramAdmin` enrols an employee by supplying `program_id`, `group_id`, `full_name`, and `email`, plus an optional `personal_card_on_file` flag that defaults to false. The named group must belong to the named program, or the enrolment fails with `ERR_PROGRAM_SCOPE_MISMATCH`. The work email must be unique within the program, compared case-insensitively, and a duplicate is `ERR_DUPLICATE_NAME`; that same email doubles as a deterministic tie-breaker when a group delivery fee is split, so it matters beyond identity. A new employee starts `ACTIVE` with `ytd_imputed_cents` of 0 and `tax_treatment_flag` of `NONE`.

Deactivation is the only transition out of `ACTIVE`, and it is a draining operation rather than a deletion. It is refused with `ERR_EMPLOYEE_HAS_OPEN_ORDERS` while the employee still holds any order in `PLACED` or `CONFIRMED`, because a deactivation must never orphan a live reservation. When it succeeds, the employee moves `ACTIVE → INACTIVE`, and as a cascade every one of that employee's `OPEN` benefit periods moves to `GRACE`, with each affected period's `version` incremented by 1 and `updated_at` refreshed. `INACTIVE` is terminal.

Opening a benefit period is how budget reaches an employee. The administrator supplies `employee_id`, `period_month` in `YYYY-MM` form, and optionally `predecessor_period_id`. The month string must match a four-digit year, a hyphen, and a two-digit month between 01 and 12, and one employee may hold at most one period per month — a repeat is `ERR_DUPLICATE_PERIOD_MONTH`. At open, the server pins `budget_rule_id` from the employee's group's currently `ACTIVE` rule; if the group has no active rule there is nothing to pin and the open fails with `ERR_NO_ACTIVE_BUDGET_RULE`.

Rollover is drawn in through the self-referential predecessor link. When `predecessor_period_id` is supplied it must name a period belonging to the same employee, in status `CLOSED`, whose `period_month` is strictly earlier than the new period's; anything else is `ERR_PREDECESSOR_NOT_CLOSED`, and a predecessor already claimed by some other period is `ERR_PREDECESSOR_ALREADY_CONSUMED`, since carry-forward cents may be spent exactly once. The predecessor's `rollover_out_cents` is copied into the new period's `rollover_in_cents`; with no predecessor, `rollover_in_cents` is 0. The period's `allocated_cents` is then the pinned rule's `monthly_allocation_cents` plus `rollover_in_cents`, and `available_cents` opens at that same figure, with `reserved_cents`, `spent_cents`, `forfeited_cents`, and `rollover_out_cents` all at 0. Opening a period also recomputes the program's `program_reserved_cents`. The period opens in `OPEN`.

### 3.4. Choosing Where to Eat: Eligibility, Radius and Order Drafting

Before an employee commits to a restaurant, they can ask the program which restaurants a given dock may order from, naming the dock through a `delivery_location_id` query parameter. The search runs three filters and then a deterministic ranking. First, cuisine: the restaurant's `cuisine` must be a member of the program's `eligible_cuisines`. Second, status: the restaurant's `status` must be `ELIGIBLE`. Third, reach: the straight-line planar distance between the restaurant's coordinates and the dock's coordinates — the square root of the sum of the squared difference in `grid_x_km` and the squared difference in `grid_y_km`, rounded half-up to three decimal places — must be less than or equal to the effective limit for that restaurant, which is the smaller of the program's `max_delivery_radius_km` and the restaurant's own `delivery_radius_km`. Equality with the effective limit passes. Survivors are ranked by that rounded distance ascending and, where two restaurants tie on distance, by `name` ascending; the identifier is never a sort key. When nothing qualifies, the answer is a successful empty array with `total_count` of 0 — an empty result is not a not-found.

Drafting an order is deliberately cheap: it records intent and computes no money. The employee supplies `employee_id`, `benefit_period_id`, `restaurant_id`, `delivery_location_id`, `requested_delivery_at`, and `lines`, and may supply `group_order_id` to attach the order to a group order and `tip_cents` to add a voluntary tip. The tip is optional, defaults to 0, and may not be negative. `requested_delivery_at` is the UTC instant the food is wanted and is the input to the weekday and window checks applied later at placement. `lines` is an ordered array of between 1 and 20 line objects, each with an `item_name` string, a `unit_price_cents` integer of at least 1, and a `quantity` integer of at least 1. Positional order in that array is meaningful twice over: it is the order in which per-line tax is rounded, and the zero-based position of a line is the addressing key a missing-item claim uses.

Several referential rules are checked at draft time. The named benefit period must belong to the named employee, or the draft is `ERR_PERIOD_EMPLOYEE_MISMATCH` — an order may not spend somebody else's budget. The employee, benefit period, and dock must all sit in the same meal program, or the draft is `ERR_PROGRAM_SCOPE_MISMATCH`. When `group_order_id` is present, the group order must still be `COLLECTING`, or the draft is `ERR_GROUP_ORDER_NOT_COLLECTING`; the logical clock must be strictly before the group order's `cutoff_at`, or the draft is `ERR_GROUP_CUTOFF_PASSED`; and the member order's `restaurant_id` and `delivery_location_id` must both equal the group order's, or the draft is `ERR_GROUP_ORDER_MISMATCH`, because one group order is one consolidated delivery from one restaurant to one dock. A draft is created with `fulfillment_status` of `DRAFT` and `settlement_status` of `UNSETTLED`; no budget is reserved and no fee is assessed until placement.

An employee may only draft, place, cancel, or read their own orders, and a restaurant may only act on orders addressed to itself; violations are `ERR_FORBIDDEN_RESOURCE`. Orders may be listed and filtered by `employee_id`, `benefit_period_id`, `restaurant_id`, `delivery_location_id`, `group_order_id`, `fulfillment_status`, or `settlement_status`, so both dimensions of the parallel state machine are independently queryable.

### 3.5. Placement: The Five-Stage Money Pipeline and Budget Reservation

Placement is the moment the order becomes money. The employee supplies `expected_benefit_period_version`, the period `version` they last observed, and the order must be in `DRAFT` — a second placement attempt is `ERR_INVALID_STATE`. The eligibility gates then run in the ladder order of §2.10: the period must be `OPEN`, so a period already in `GRACE` accepts no new placement and reports `ERR_PERIOD_NOT_OPEN`; the employee must be `ACTIVE`; the restaurant must be `ELIGIBLE`, so a suspension between draft and placement blocks the placement with `ERR_RESTAURANT_NOT_ELIGIBLE`; a member order's group order must still be `COLLECTING`; and the supplied expected version must match. Then the temporal gates: the ISO weekday of `requested_delivery_at` must be in the pinned rule's `eligible_weekdays`, its minute-of-day must fall in the half-open eligible window, and, for a member order, the clock must still be strictly before `cutoff_at` — exactly at `cutoff_at` is already too late. Then the reach and allow-list checks of §3.4 are re-applied to this specific pairing, yielding `ERR_RESTAURANT_OUT_OF_RANGE` or `ERR_CUISINE_NOT_ELIGIBLE`. Then the daily ceiling: counting the employee's orders on the requested UTC calendar date that are `PLACED`, `CONFIRMED`, or `DELIVERED`, that count must be strictly below the pinned rule's `daily_meal_limit`, or the placement is `ERR_DAILY_MEAL_LIMIT_EXCEEDED`. Cancelled orders do not count, so cancelling frees a slot for the same day.

Only once every gate above has passed does pricing run, and it runs in exactly four stages in this order.

**Stage one — line tax and subtotal.** Walk `lines` in positional order. For each line, the line base is `unit_price_cents` multiplied by `quantity`. `subtotal_cents` is the sum of those line bases. `tax_cents` is computed differently: for each line, multiply that line's base by the sales tax rate of 8.75 percent, round the product half-up to a whole cent, and add the rounded figure to a running total. Rounding happens once per line, before summation, and this is the pinned contract. Applying the rate to the whole subtotal and rounding once at the end is *not* the contract and differs observably whenever discarded fractions accumulate past half a cent: three lines of 1,000 cents each produce 88 plus 88 plus 88, for a `tax_cents` of 264, where a single rounding of the 3,000-cent subtotal would have produced 263.

**Stage two — fees.** `delivery_fee_cents` depends on whether the order is solo. For a member order the delivery fee is this order's share of the consolidated group fee, which is 0 until the group order is submitted. For a solo order, a `subtotal_cents` of at least the free-delivery threshold of 3,500 cents earns free delivery and `delivery_fee_cents` of 0; below that threshold the flat base delivery fee of 599 cents applies. `service_fee_cents` is a three-stage composition and the stage order is pinned. Stage 2a computes a raw fee as 10 percent of `subtotal_cents` — the subtotal alone, not the taxed base — rounded half-up to a whole cent. Stage 2b clamps that raw figure into the range from 99 cents to 500 cents inclusive: anything below 99 becomes 99, anything above 500 becomes 500. Stage 2c applies a volume discount whose tier is selected from the pre-fee base, meaning `subtotal_cents` plus `tax_cents`: a pre-fee base of at least 12,000 cents earns a 25 percent discount, a pre-fee base of at least 5,000 cents but below 12,000 earns a 10 percent discount, and anything below 5,000 earns no discount. The discount amount is the clamped fee multiplied by the discount rate, rounded half-up to a whole cent, and `service_fee_cents` is the clamped fee minus that discount amount. The discount never re-selects a tier and never re-clamps. Clamp-then-discount is the contract and discount-then-clamp is observably wrong: with a subtotal of 6,000 and tax of 524, the raw fee is 600, the clamped fee is 500, the tier rate is 10 percent, and the service fee is 500 minus 50, which is 450 — whereas discounting first would give 540 and then clamp back up to 500.

**Stage three — the employer/employee split.** `tip_covered_by_employer_cents` is equal to `tip_cents` when the pinned rule's `tip_coverage_policy` is `EMPLOYER_COVERS_TIP`, and 0 when it is `EMPLOYEE_PAYS_TIP`. `covered_base_cents`, the employer-eligible base, is the sum of `subtotal_cents`, `tax_cents`, `delivery_fee_cents`, `service_fee_cents`, and `tip_covered_by_employer_cents`. `employer_covered_cents` is the smallest of three independent ceilings: the covered base itself, the pinned rule's `per_meal_cap_cents`, and the period's `available_cents`. `employee_card_cents` is the part of the covered base the employer did not take — the covered base minus the employer share — plus the part of the tip the employer did not admit, which is `tip_cents` minus `tip_covered_by_employer_cents`. `gross_total_cents`, the customer-facing total, is `covered_base_cents` plus `tip_cents` minus `tip_covered_by_employer_cents`; it excludes the administration fee entirely. No rounding occurs anywhere in this stage — only selection among ceilings.

Three fiscal gates then run on the computed split, in this order. If `employee_card_cents` is positive and the pinned `overage_policy` is `BLOCK`, the placement is refused with `ERR_OVERAGE_NOT_PERMITTED`. Note that landing exactly at the cap is not an overage: when `covered_base_cents` equals `per_meal_cap_cents` the employee card amount is 0 apart from any uncovered tip, and a `BLOCK` group still succeeds. Next, if the period's `available_cents` is below the smaller of the covered base and the per-meal cap, the placement is refused with `ERR_PERIOD_BUDGET_EXCEEDED` — an exhausted period never silently truncates the employer share, it refuses the order. Last, if `employee_card_cents` is positive and the employee's `personal_card_on_file` is false, the placement is refused with `ERR_PERSONAL_CARD_REQUIRED`, which is the only condition in this system answered with HTTP 402.

**Stage four — the administration fee.** `admin_fee_cents` is the employer-billed program administration fee. Its rate is selected from the program's `mtd_employer_captured_cents` *as it stands before this order's own employer share is added*: a month-to-date captured figure of at least 500,000 cents — five thousand dollars — prices at 3 percent, at least 100,000 cents but below 500,000 prices at 4 percent, and below 100,000 cents prices at 5 percent. The fee is `employer_covered_cents` multiplied by that rate, rounded half-up to a whole cent. Because the tier is read before the order's own contribution lands, the very order that crosses a tier boundary is still priced at the old, higher tier. The administration fee is never part of `covered_base_cents`, is never charged to the employee, and is zeroed if the order is voided.

A successful placement then commits its side effects. `placed_at` is stamped with the current logical clock. `fulfillment_status` moves `DRAFT → PLACED` and, in the settlement dimension, `settlement_status` moves `UNSETTLED → SPLIT_AUTHORIZED`. Reaching `SPLIT_AUTHORIZED` freezes `employer_covered_cents`, `employee_card_cents`, and `admin_fee_cents` as the authorised split. The period's `reserved_cents` increases by `employer_covered_cents` and its `available_cents` decreases by the same amount, keeping the partition identity intact, and the period's `version` increments by 1. The program's `program_reserved_cents` is recomputed. When `group_order_id` is present, the group order's `member_order_count` increases by 1.

### 3.6. Group Order Coordination: Locking, Reopening and Consolidated Submission

An `Employee` opens a group order to consolidate one delivery for several colleagues. The organiser supplies `program_id`, `organizer_employee_id`, `restaurant_id`, `delivery_location_id`, `cutoff_at`, `window_start`, `window_end`, and `per_person_limit_cents`. `cutoff_at` is the last instant at which a member order may join, and it must fall strictly before `window_start`; joining at or after `cutoff_at` is already too late. `window_start` is the inclusive start of the consolidated delivery window and `window_end`, which must fall strictly after it, is its end. `per_person_limit_cents` is a ceiling of at least 1 cent on each member order's pre-fee base — that is, on `subtotal_cents` plus `tax_cents` — and it is independent of, and typically stricter than, the budget rule's per-meal cap; the fees a member order will later attract do not count against it. Creating a group order requires the organiser to be `ACTIVE`, or the request is `ERR_EMPLOYEE_INACTIVE`, and the chosen restaurant must pass both the cuisine allow-list and the two-sided radius test against the chosen dock, or the request is `ERR_CUISINE_NOT_ELIGIBLE` or `ERR_RESTAURANT_OUT_OF_RANGE`. All referenced rows must belong to the named program. A new group order is `COLLECTING` with `member_order_count` of 0, `reopen_count` of 0, and `allocated_delivery_fee_cents` of 0.

The organiser — and only the organiser, since any other employee is `ERR_FORBIDDEN_RESOURCE` — freezes the roster by locking the group order, moving it `COLLECTING → LOCKED`. A lock requires at least one attached member order; locking an empty group order is `ERR_GROUP_ORDER_EMPTY`. While `LOCKED`, no further member order may attach or place. The organiser may reverse that decision by reopening, moving the group order `LOCKED → COLLECTING` and incrementing `reopen_count` by 1. Reopening is bounded twice over: the logical clock must still be strictly before `cutoff_at`, or the request is `ERR_GROUP_CUTOFF_PASSED`, and `reopen_count` must still be below the reopen ceiling of 2, so a group order may cycle back into collection at most twice and a third attempt is `ERR_REOPEN_LIMIT_EXCEEDED`. Both lock and reopen increment the group order's `version` by 1.

Submission is the consolidation, and it moves the group order `LOCKED → SUBMITTED`, a terminal state. It requires at least one attached member order, so an emptied group order cannot be submitted and reports `ERR_GROUP_ORDER_EMPTY`, and it requires the restaurant to still be `ELIGIBLE`, reporting `ERR_RESTAURANT_NOT_ELIGIBLE` otherwise. Two overlap tests then run, and they are deliberately *not* the same shape, which is the subtlest rule in this domain.

Restaurant capacity uses **half-open** windows. Count the already-`SUBMITTED` group orders at the same restaurant whose interval from `window_start` up to but excluding `window_end` intersects this group order's interval on the same basis. That count must be strictly below the restaurant's `max_concurrent_group_deliveries`, or the submission is `ERR_RESTAURANT_CAPACITY_EXCEEDED`. Because the intervals are half-open, a window that begins at exactly the instant another ends does not intersect it and consumes no capacity.

Dock occupancy uses a **closed** interval with a trailing buffer. This group order occupies its dock from `window_start` through `window_end` plus the dock's `dock_buffer_minutes`, inclusive at both ends. If any other `SUBMITTED` group order occupies the same dock over an interval computed the same way and the two intervals share even a single instant, the submission is `ERR_DOCK_WINDOW_CONFLICT`; the dock admits one consolidated delivery at a time regardless of any capacity number. The consequence is that the very same pair of adjacent windows can be perfectly legal for restaurant capacity and simultaneously illegal for the dock, and both tests must be applied independently.

When both tests pass, the consolidated delivery fee is allocated. The group delivery fee is a flat 1,250 cents for the whole delivery, and it is divided across the non-cancelled member orders with a deterministic remainder waterfall. Let the member count be the number of non-cancelled member orders. The base share is the group delivery fee divided by that count, discarding any fraction. The remainder is the group delivery fee minus the base share multiplied by the member count. Order the members by `created_at` ascending and, where two were created at the same instant, by the ordering employee's `email` ascending — never by identifier. Then walk that ordered list from the front: each of the first *remainder*-many members receives the base share plus one cent as its `delivery_fee_cents`, and every member after that receives exactly the base share. The sum of member `delivery_fee_cents` therefore equals the group delivery fee exactly. With three members the shares are 417, 417, and 416 — never three times 416 and never three times 417.

Allocation is followed by a full re-pricing of every member order, because a member's delivery fee has just changed from 0 to a real number. For each member order, the fee assessment, the employer/employee split, and the administration fee are re-run in that order, using that member's newly assigned `delivery_fee_cents`. Each member's benefit period then has its `reserved_cents` adjusted by the delta in that order's `employer_covered_cents`, with `available_cents` moving by the same amount in the opposite direction, and each affected period's `version` increments by 1. The group order's `allocated_delivery_fee_cents` is set to the full 1,250 cents. Because the split is recomputed, the three fiscal gates apply again at submission: a member order that now overruns a `BLOCK` group's cap yields `ERR_OVERAGE_NOT_PERMITTED`, one that now outruns its period's `available_cents` yields `ERR_PERIOD_BUDGET_EXCEEDED`, and one that now needs a personal card the employee does not have yields `ERR_PERSONAL_CARD_REQUIRED`.

The organiser may instead cancel the group order, from either `COLLECTING` or `LOCKED`, moving it to the terminal `CANCELLED`. Cancellation cascades: every attached member order that is still `DRAFT` or `PLACED` is cancelled too, each placed one releasing its `employer_covered_cents` from its period's `reserved_cents` back to `available_cents` and incrementing that period's `version` by 1, exactly as an individual cancellation would. A submitted group order cannot be cancelled, and neither can an already-cancelled one; either attempt is `ERR_INVALID_STATE`.

### 3.7. Fulfilment, Capture and Taxable Benefit Accrual

A `Restaurant` whose identifier matches the order's `restaurant_id` confirms a placed order, moving it `PLACED → CONFIRMED`. Confirmation requires the restaurant to still be `ELIGIBLE` and moves no money at all: the reservation stays exactly where it is, on the period's `reserved_cents`.

Delivery is where employer money is captured and where the taxable benefit is born. The same restaurant delivers a confirmed order, moving `fulfillment_status` `CONFIRMED → DELIVERED` and, in the settlement dimension, `settlement_status` `SPLIT_AUTHORIZED → CAPTURED`. Delivery is refused with `ERR_TAX_MONTH_LOCKED` if the employee's imputed-income bucket for the order's month already exists and is `LOCKED` or `EXPORTED`; payroll having taken the month is final. On success, `delivered_at` is stamped with the logical clock, `net_charged_cents` is set to `gross_total_cents`, and `employer_net_cents` is set to `employer_covered_cents`. The period's `reserved_cents` decreases by `employer_covered_cents` while its `spent_cents` increases by the same amount — the money changes bucket without changing the partition total — and the period's `version` increments by 1.

The order's `tax_month` is the `YYYY-MM` bucket derived from `requested_delivery_at`, and it is the key under which both imputed income and expense exports are grouped. If the employee has no `ImputedIncomeRecord` for that `tax_month`, delivery creates one lazily, in status `ACCRUING`, with its `employee_id` and `tax_month` set and its `method` pinned from the program's `taxable_benefit_method` as it reads at that moment. Accrual then runs. Under the `DE_MINIMIS_EXCLUSION` method, only the part of the employer share above the per-meal de-minimis floor of 2,000 cents — twenty dollars — is taxable, and the taxable amount never goes below zero: an employer share of 2,500 cents yields `taxable_cents` of 500, and an employer share of 1,800 cents yields 0. Under the `FULL_INCLUSION` method the whole employer share is taxable, so the same 2,500-cent employer share yields `taxable_cents` of 2,500 — a difference of exactly 2,000 cents on that order. The record's `taxable_cents` is the sum of `taxable_cents` over the month's delivered orders and its `gross_employer_paid_cents` is the sum of `employer_net_cents` over the same orders.

The employee's `ytd_imputed_cents` is then re-derived as the sum of `taxable_cents` across all of that employee's imputed-income records, and `tax_treatment_flag` is re-derived from it: the flag reads `W2_IMPUTED` once `ytd_imputed_cents` reaches the reporting threshold of 1,000 cents — ten dollars — and reads `NONE` below that. The flag is re-derived rather than latched, so a later refund that pulls the year-to-date figure back below the threshold returns the flag to `NONE`. Finally the program rollups `program_spent_cents`, `program_reserved_cents`, and `mtd_employer_captured_cents` are all recomputed.

`ImputedIncomeRecord` never advances by direct request; its status is moved only by cascades. It goes `ACCRUING → LOCKED` when a benefit period for the matching month is finally closed, and `LOCKED → EXPORTED` when a payroll-format export covering its `tax_month` is generated, as described in §3.9. `EXPORTED` is terminal.

### 3.8. Cancellation, Voiding and Credit Claim Routing

Cancellation before delivery has three flavours distinguished by the state it starts from, and the actor differs at the end. An `Employee` may cancel their own order from `DRAFT`, which moves `fulfillment_status` to `CANCELLED` and `settlement_status` `UNSETTLED → VOIDED` with no ledger entries whatsoever — a never-authorised order leaves no money trail. An `Employee` may also cancel from `PLACED`: that releases `employer_covered_cents` from the period's `reserved_cents` back to `available_cents`, increments the period's `version` by 1, moves `settlement_status` `SPLIT_AUTHORIZED → VOIDED`, and, when `group_order_id` is present, decrements the group order's `member_order_count` by 1. Once an order is `CONFIRMED`, the employee can no longer cancel it; only a `ProgramAdmin` may, and the money effects are identical to the placed case. `CANCELLED` is terminal in the fulfilment dimension, as `VOIDED` is in the settlement dimension.

Voiding an order that had an authorised split writes the reversal into the immutable refund ledger. A `RefundLedgerEntry` is appended with `direction` of `EMPLOYER_CREDIT` and `amount_cents` equal to `employer_covered_cents` whenever that figure is greater than 0, and a second entry with `direction` of `EMPLOYEE_CARD_REFUND` and `amount_cents` equal to `employee_card_cents` whenever that figure is greater than 0; both carry `reason` of `ORDER_VOID` and both leave `credit_claim_id` absent, because no claim drove them. Each entry also records the `order_id` whose money moved and a `created_at` at the logical instant of the movement, and `amount_cents` is always a positive number of cents. The void then zeroes `net_charged_cents`, `employer_net_cents`, and `admin_fee_cents`. The ledger entries written against an order, and those written by a particular claim's settlement, are both readable and may be filtered by `direction` and by `reason`.

A delivered order that arrived wrong is disputed through a credit claim. An `Employee` raises one against their own delivered order, supplying `order_id`, `claim_type`, and `claimed_cents`, plus `line_index` where the claim type demands it. `claim_type` is one of `MISSING_ITEM`, `QUALITY_ISSUE`, or `NEVER_DELIVERED`. `line_index` is the zero-based position in the order's `lines`; it is required and must address an existing line for `MISSING_ITEM`, and it is forbidden for `NEVER_DELIVERED`, with either mistake reported as `ERR_LINE_INDEX_INVALID`. `claimed_cents` must be at least 1 and must not exceed the order's remaining refundable amount; for a `MISSING_ITEM` claim it must additionally not exceed the addressed line's base plus that line's own rounded tax, computed exactly as stage one of §3.5 computed it. Either overreach is `ERR_CLAIM_EXCEEDS_ORDER`. A claim is created in `SUBMITTED` with `approved_cents` of 0.

Resolution is a `BenefitsController` decision and it forks three ways on a `decision` input of `APPROVE` or `DENY`. Every resolution requires `expected_order_version` to match the order's current `version`, or it is `ERR_STALE_ORDER_VERSION`, and every resolution is refused with `ERR_TAX_MONTH_LOCKED` if the order's month bucket is `LOCKED` or `EXPORTED`. An approval requires the order to be `DELIVERED` and carries `approved_cents`, which must be at least 1 and at most `claimed_cents`, and `routing_basis`, which selects the variant. An approval with `routing_basis` of `EMPLOYEE_FIRST` moves the claim `SUBMITTED → ROUTED_EMPLOYEE_FIRST`; an approval with `routing_basis` of `PROPORTIONAL` moves it `SUBMITTED → ROUTED_PROPORTIONAL`. Both store `approved_cents`, `routing_basis`, and the resolver's `resolved_by_user_id`, both compute the routing split immediately, and both increment the order's `version` by 1. A `DENY` decision moves the claim `SUBMITTED → DENIED`, sets `approved_cents`, `employer_credit_cents`, and `employee_refund_cents` all to 0, stores `resolved_by_user_id`, writes no ledger entries, and moves no money. `DENIED` is terminal.

The routing split itself has two variants, and the employer side absorbs the rounding residue in both, so `employee_refund_cents` plus `employer_credit_cents` always equals `approved_cents` exactly. Under `EMPLOYEE_FIRST`, the employee is made whole before the employer receives anything: `employee_refund_cents` is the smaller of `approved_cents` and the employee's remaining personal-card exposure, which is `employee_card_cents` minus `employee_refunded_cents`; `employer_credit_cents` is `approved_cents` minus that figure. Under `PROPORTIONAL`, the credit is split by the original charge ratio: `employee_refund_cents` is `approved_cents` multiplied by `employee_card_cents` and divided by `gross_total_cents`, rounded half-up to a whole cent, and `employer_credit_cents` is `approved_cents` minus that figure. The two variants diverge sharply. On an order with `employee_card_cents` of 1,863, `employer_covered_cents` of 2,500, and `gross_total_cents` of 4,363, an approved amount of 1,000 routes as 1,000 to the employee and 0 to the employer under `EMPLOYEE_FIRST`, but as 427 to the employee and 573 to the employer under `PROPORTIONAL`.

Settlement is the second pair of eyes and the moment money actually moves. A `BenefitsController` whose identifier differs from `resolved_by_user_id` settles a claim from either routed state — `ROUTED_EMPLOYEE_FIRST` or `ROUTED_PROPORTIONAL` — joining both branches into the terminal `SETTLED`; a same-person attempt is `ERR_SEGREGATION_OF_DUTIES` and a settlement against a `LOCKED` or `EXPORTED` month is `ERR_TAX_MONTH_LOCKED`. Settlement appends one or two `RefundLedgerEntry` rows with `reason` of `CLAIM_SETTLEMENT` and `credit_claim_id` naming the claim: an `EMPLOYER_CREDIT` entry for `employer_credit_cents` and an `EMPLOYEE_CARD_REFUND` entry for `employee_refund_cents`, each written only when its amount is greater than 0. It then re-derives `employer_refunded_cents` and `employee_refunded_cents` as the cumulative credits issued against the order, recomputes `net_charged_cents` as `gross_total_cents` less both cumulative figures, and recomputes `employer_net_cents` as `employer_covered_cents` less `employer_refunded_cents` — the figure that lands in the period's `spent_cents`. The period's `spent_cents` decreases by `employer_credit_cents` and its `available_cents` increases by the same amount, returning employer money to the budget. Accrual is then re-run on the reduced `employer_net_cents`, reconciling the imputed-income record's `taxable_cents` and `gross_employer_paid_cents` and the employee's `ytd_imputed_cents` and `tax_treatment_flag`. The order's `version` increments by 1.

The order's settlement dimension advances according to how much of the order has now been refunded. When the cumulative refund after this settlement — `employer_refunded_cents` plus `employee_refunded_cents` plus the newly approved amount — remains strictly below `gross_total_cents`, the order moves `CAPTURED → PARTIALLY_REFUNDED`; a further such settlement keeps it at `PARTIALLY_REFUNDED`, with the ledger simply accumulating. When that cumulative refund equals `gross_total_cents` exactly, the order moves to `REFUNDED` — from `CAPTURED` directly if this is the first settlement, or from `PARTIALLY_REFUNDED` if earlier ones came first — and `net_charged_cents` becomes 0. `REFUNDED` is terminal in the settlement dimension, which is what stops an order from being refunded past its own total.

### 3.9. Period Close, Forfeiture, Forecasting and Expense Export

A `ProgramAdmin` closes a benefit period in one of two modes, supplied as `mode`. Mode `GRACE` moves the period `OPEN → GRACE`, increments its `version` by 1, and does exactly one thing: it stops new placements while leaving in-flight `PLACED` and `CONFIRMED` orders free to be confirmed and delivered. It is never blocked by open orders — draining them is its entire purpose.

Mode `FINAL` moves the period to the terminal `CLOSED`, and it may be requested from either `OPEN` or `GRACE` with identical effects. A final close is refused with `ERR_PERIOD_HAS_OPEN_ORDERS` while any attached order is still `PLACED` or `CONFIRMED`, which is why `reserved_cents` is necessarily 0 by the time the close runs. The unused money is then the period's `available_cents`, and it is carved into two parts according to the program's `rollover_policy`. Under `NONE`, `rollover_out_cents` is 0. Under `FULL`, `rollover_out_cents` is the whole unused amount. Under `CAPPED_PCT`, the cap is `allocated_cents` multiplied by `rollover_cap_pct`, rounded half-up to a whole cent, and `rollover_out_cents` is the smaller of the unused amount and that cap. `forfeited_cents` is then the unused amount minus `rollover_out_cents`, and `available_cents` is driven to 0, which restores the partition identity of §2.7 exactly. A period allocated 50,000 cents that spent 2,500 has 47,500 unused; under a 25 percent cap that is a cap of 12,500, so `rollover_out_cents` is 12,500 and `forfeited_cents` is 35,000. A successor period naming it as predecessor then opens with `rollover_in_cents` of 12,500 and `allocated_cents` of 62,500.

A final close also increments the period's `version` by 1, recomputes the program's `program_reserved_cents`, and cascades to payroll: every `ImputedIncomeRecord` belonging to that period's employee whose `tax_month` equals the period's `period_month` and whose status is `ACCRUING` moves `ACCRUING → LOCKED`. From that point on, further accrual against the month and further claim settlement touching it are both refused with `ERR_TAX_MONTH_LOCKED`.

Forecasting answers what the employer's spend for the current logical month will total. The forecast reads the program's `forecast_basis` live and returns `forecast_basis`, `forecast_total_cents`, `forecast_admin_fee_cents`, `remaining_eligible_days`, `elapsed_eligible_days`, `total_eligible_days`, and `active_rule_group_count`. Only employee groups that currently have a budget rule in `ACTIVE` status participate, and `active_rule_group_count` is how many those are. Three day counts are computed over the logical clock's UTC calendar month: for a given rule, its remaining eligible days are the dates from today through the last day of the month whose ISO weekday appears in that rule's `eligible_weekdays`; the elapsed eligible days are the dates from the first day of the month through today whose ISO weekday appears in the union of `eligible_weekdays` across all participating rules; and the total eligible days are the dates anywhere in the month whose ISO weekday appears in that same union. Today counts in both the remaining and the elapsed tally.

Under the `COMMITMENT` basis, the committed amount is summed over participating groups, each contributing its `headcount_planned` multiplied by its rule's `daily_meal_limit`, multiplied by its rule's `per_meal_cap_cents`, multiplied by that rule's remaining eligible days. A ceiling is summed in parallel: each group contributes its `headcount_planned` multiplied by its rule's `monthly_allocation_cents`, and the program's `program_spent_cents` is subtracted from that sum. `forecast_total_cents` is the smaller of the committed amount and the ceiling, plus `program_spent_cents`. Under the `RUN_RATE` basis, `forecast_total_cents` is `program_spent_cents` divided by the elapsed eligible days and multiplied by the total eligible days, rounded half-up once at the end, and it is 0 when the elapsed eligible day count is 0. In both cases `forecast_admin_fee_cents` is `forecast_total_cents` multiplied by the administration rate implied by the program's current `mtd_employer_captured_cents` under the tier table of §3.5, rounded half-up to a whole cent. The two bases diverge by an order of magnitude on the same data: on the tenth of August 2026, with a single participating group of two planned heads, a daily limit of 1, a cap of 2,500 cents, weekdays Monday through Friday, an allocation of 50,000 cents, and `program_spent_cents` of 2,500, the remaining eligible days are 16, the elapsed are 6, and the total is 21; `COMMITMENT` gives a committed 80,000 against a ceiling of 97,500, so `forecast_total_cents` is 82,500 with an administration fee of 4,125, while `RUN_RATE` gives 8,750 with a fee of 438.

Expense reporting is a `BenefitsController` operation. Generating an export names the `tax_month` to roll up, in `YYYY-MM` form, and the `format`, which is either `CSV_EXPENSE_REPORT` for the finance system or `PAYROLL_IMPUTED_FEED` for payroll. The bucket is the program's delivered, non-voided orders whose `tax_month` matches. `receipt_count` is the number of orders in the bucket; `employer_gross_cents` is the sum of their `employer_covered_cents`; `employer_refund_cents` is the sum of their `employer_refunded_cents`; `net_of_refunds_cents` is `employer_gross_cents` minus `employer_refund_cents`; `admin_fee_total_cents` is the sum of their `admin_fee_cents`; and `imputed_total_cents` is the sum of their `taxable_cents`. Nothing here is rounded — these are pure summations. An empty bucket is not a zero-valued success: when `receipt_count` is 0 the export is created with status `FAILED` instead of `GENERATED`. When the format is `PAYROLL_IMPUTED_FEED` and the export is `GENERATED`, every `LOCKED` imputed-income record whose `tax_month` matches the export's cascades `LOCKED → EXPORTED`, freezing it for payroll and folding its `taxable_cents` into the export's `imputed_total_cents`.

Downstream acceptance is recorded by acknowledging a `GENERATED` export, which moves it `GENERATED → ACKNOWLEDGED`, increments its `version` by 1, and makes it immutable. `ACKNOWLEDGED` and `FAILED` are both terminal, so a failed export can never be acknowledged and reports `ERR_INVALID_STATE`. Exports may be listed and filtered by `tax_month` and by `status`.

## 4. Endpoint Definitions

The table below is a routing summary only. Request payloads, response payloads, cascades, and validation conditions are specified in §2 and §3 and are not repeated here. Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200. Error responses use the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| `POST` | `/_clock/set_current_utc` | Sets the logical current UTC instant used by every temporal rule. The default clock, before any call to this endpoint, is 2026-08-01T00:00:00Z. | `PlatformAdmin`, `ProgramAdmin` |
| `POST` | `/meal-programs` | Creates a meal stipend program (tenant root). | `PlatformAdmin` |
| `GET` | `/meal-programs/{id}` | Reads a program with its live rollups. | `PlatformAdmin`, `ProgramAdmin`, `BenefitsController` |
| `PATCH` | `/meal-programs/{id}` | Updates program-level policy selectors. Does not retroactively re-derive existing orders or pinned imputed-income methods. | `PlatformAdmin` |
| `POST` | `/meal-programs/{id}/employee-groups` | Creates an employee group under the program. | `ProgramAdmin` |
| `GET` | `/meal-programs/{id}/employee-groups` | Lists the program's employee groups. | `PlatformAdmin`, `ProgramAdmin`, `BenefitsController` |
| `POST` | `/meal-programs/{id}/delivery-locations` | Creates a delivery dock for the program. | `ProgramAdmin` |
| `GET` | `/meal-programs/{id}/delivery-locations` | Lists the program's delivery docks. | `PlatformAdmin`, `ProgramAdmin`, `BenefitsController`, `Employee` |
| `GET` | `/meal-programs/{id}/eligible-restaurants` | Runs the eligibility selection for a delivery location and returns the ranked eligible restaurants. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `GET` | `/meal-programs/{id}/forecast` | Runs the program cost forecast under the program's current forecast basis. | `ProgramAdmin`, `BenefitsController` |
| `POST` | `/meal-programs/{id}/expense-exports` | Generates an expense / payroll export for one tax month. | `BenefitsController` |
| `GET` | `/meal-programs/{id}/expense-exports` | Lists the program's exports. | `ProgramAdmin`, `BenefitsController` |
| `POST` | `/expense-exports/{id}/acknowledge` | Records downstream acceptance of a generated export. | `BenefitsController` |
| `GET` | `/employee-groups/{id}` | Reads an employee group. | `PlatformAdmin`, `ProgramAdmin`, `BenefitsController` |
| `POST` | `/employee-groups/{id}/budget-rules` | Drafts a budget rule for the group. | `BenefitsController` |
| `GET` | `/employee-groups/{id}/budget-rules` | Lists the group's budget rules. | `PlatformAdmin`, `ProgramAdmin`, `BenefitsController` |
| `POST` | `/budget-rules/{id}/activate` | Activates a drafted budget rule under optimistic concurrency on the owning employee group. | `BenefitsController` |
| `POST` | `/employees` | Enrolls an employee in a program and group. | `ProgramAdmin` |
| `GET` | `/employees/{id}` | Reads an employee. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `GET` | `/employees` | Lists employees, filterable by program and group. | `PlatformAdmin`, `ProgramAdmin`, `BenefitsController` |
| `POST` | `/employees/{id}/deactivate` | Deactivates an employee and drains their open budget periods. | `ProgramAdmin` |
| `GET` | `/employees/{id}/imputed-income-records` | Lists the employee's monthly imputed income records. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `POST` | `/restaurants` | Registers a restaurant on the platform. | `PlatformAdmin` |
| `GET` | `/restaurants/{id}` | Reads a restaurant. | `PlatformAdmin`, `ProgramAdmin`, `BenefitsController`, `Employee`, `Restaurant` |
| `PATCH` | `/restaurants/{id}` | Suspends or reinstates a restaurant. | `PlatformAdmin` |
| `POST` | `/benefit-periods` | Opens a monthly benefit period, pinning the employee group's active budget rule and drawing any predecessor rollover. | `ProgramAdmin` |
| `GET` | `/benefit-periods/{id}` | Reads a benefit period with its live budget partition. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `GET` | `/benefit-periods` | Lists benefit periods, filterable by employee, pinned rule and predecessor. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `POST` | `/benefit-periods/{id}/close` | Moves the period to `GRACE` or performs a final close with rollover and forfeiture. | `ProgramAdmin` |
| `POST` | `/orders` | Drafts an order, optionally attaching it to a group order as a member order. | `Employee` |
| `GET` | `/orders/{id}` | Reads an order with its full money breakdown. | `ProgramAdmin`, `BenefitsController`, `Employee`, `Restaurant` |
| `GET` | `/orders` | Lists orders, filterable by every foreign key and by either state dimension. | `ProgramAdmin`, `BenefitsController`, `Employee`, `Restaurant` |
| `POST` | `/orders/{id}/place` | Prices the order, authorises the employer/employee split and reserves employer budget, under optimistic concurrency on the benefit period. | `Employee` |
| `POST` | `/orders/{id}/confirm` | Restaurant accepts a placed order. | `Restaurant` |
| `POST` | `/orders/{id}/deliver` | Restaurant completes delivery; captures the split and accrues imputed income. | `Restaurant` |
| `POST` | `/orders/{id}/cancel` | Cancels an order before delivery, releasing the reservation and voiding the authorised split. | `Employee`, `ProgramAdmin` |
| `GET` | `/orders/{id}/refund-entries` | Lists the immutable refund ledger entries written against the order. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `POST` | `/group-orders` | Opens a group order for a single restaurant and dock, with a join cutoff and a per-person pre-fee limit. | `Employee` |
| `GET` | `/group-orders/{id}` | Reads a group order. | `ProgramAdmin`, `BenefitsController`, `Employee`, `Restaurant` |
| `GET` | `/group-orders` | Lists group orders, filterable by every foreign key. | `ProgramAdmin`, `BenefitsController`, `Employee`, `Restaurant` |
| `POST` | `/group-orders/{id}/lock` | Organizer freezes the member list. | `Employee` |
| `POST` | `/group-orders/{id}/reopen` | Organizer reopens collection before the cutoff, up to the reopen ceiling. | `Employee` |
| `POST` | `/group-orders/{id}/submit` | Submits the consolidated delivery, allocating the group delivery fee and re-pricing every member order. | `Employee` |
| `POST` | `/group-orders/{id}/cancel` | Cancels the group order and cascades cancellation to its member orders. | `Employee` |
| `POST` | `/credit-claims` | Employee raises a missing-item, quality or non-delivery credit claim against a delivered order. | `Employee` |
| `GET` | `/credit-claims/{id}` | Reads a credit claim with its routing split. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `GET` | `/credit-claims` | Lists credit claims, filterable by order. | `ProgramAdmin`, `BenefitsController`, `Employee` |
| `POST` | `/credit-claims/{id}/resolve` | Approves the claim on a routing basis, or denies it, under optimistic concurrency on the order. | `BenefitsController` |
| `POST` | `/credit-claims/{id}/settle` | Second-person settlement: writes the refund ledger and moves the money. | `BenefitsController` |
| `GET` | `/credit-claims/{id}/refund-entries` | Lists the immutable ledger entries written by this claim's settlement. | `ProgramAdmin`, `BenefitsController`, `Employee` |

## 5. Error Code Catalogue

Trigger conditions are not repeated here; each code's condition is specified in the §2 principle or §3 workflow that raises it.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_RESOURCE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEAL_PROGRAM_NOT_FOUND` | 404 |
| `ERR_EMPLOYEE_GROUP_NOT_FOUND` | 404 |
| `ERR_BUDGET_RULE_NOT_FOUND` | 404 |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 |
| `ERR_BENEFIT_PERIOD_NOT_FOUND` | 404 |
| `ERR_RESTAURANT_NOT_FOUND` | 404 |
| `ERR_DELIVERY_LOCATION_NOT_FOUND` | 404 |
| `ERR_GROUP_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_CREDIT_CLAIM_NOT_FOUND` | 404 |
| `ERR_EXPENSE_EXPORT_NOT_FOUND` | 404 |
| `ERR_PERIOD_NOT_OPEN` | 409 |
| `ERR_EMPLOYEE_INACTIVE` | 409 |
| `ERR_RESTAURANT_NOT_ELIGIBLE` | 409 |
| `ERR_GROUP_ORDER_NOT_COLLECTING` | 409 |
| `ERR_GROUP_ORDER_EMPTY` | 409 |
| `ERR_RULE_NOT_EFFECTIVE` | 409 |
| `ERR_STALE_PERIOD_VERSION` | 412 |
| `ERR_STALE_EMPLOYEE_GROUP_VERSION` | 412 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_TAX_MONTH_LOCKED` | 409 |
| `ERR_PERIOD_HAS_OPEN_ORDERS` | 409 |
| `ERR_EMPLOYEE_HAS_OPEN_ORDERS` | 409 |
| `ERR_OUTSIDE_ELIGIBLE_WEEKDAY` | 422 |
| `ERR_OUTSIDE_ELIGIBLE_WINDOW` | 422 |
| `ERR_GROUP_CUTOFF_PASSED` | 409 |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 |
| `ERR_RESTAURANT_CAPACITY_EXCEEDED` | 409 |
| `ERR_PERIOD_EMPLOYEE_MISMATCH` | 422 |
| `ERR_PROGRAM_SCOPE_MISMATCH` | 422 |
| `ERR_GROUP_ORDER_MISMATCH` | 422 |
| `ERR_NO_ACTIVE_BUDGET_RULE` | 409 |
| `ERR_PREDECESSOR_NOT_CLOSED` | 409 |
| `ERR_PREDECESSOR_ALREADY_CONSUMED` | 409 |
| `ERR_DUPLICATE_PERIOD_MONTH` | 409 |
| `ERR_DUPLICATE_NAME` | 409 |
| `ERR_RESTAURANT_OUT_OF_RANGE` | 422 |
| `ERR_CUISINE_NOT_ELIGIBLE` | 422 |
| `ERR_DAILY_MEAL_LIMIT_EXCEEDED` | 409 |
| `ERR_PER_PERSON_LIMIT_EXCEEDED` | 422 |
| `ERR_REOPEN_LIMIT_EXCEEDED` | 409 |
| `ERR_LINE_INDEX_INVALID` | 422 |
| `ERR_CLAIM_EXCEEDS_ORDER` | 422 |
| `ERR_OVERAGE_NOT_PERMITTED` | 409 |
| `ERR_PERIOD_BUDGET_EXCEEDED` | 409 |
| `ERR_PERSONAL_CARD_REQUIRED` | 402 |
