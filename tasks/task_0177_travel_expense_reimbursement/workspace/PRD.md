# Travel Expense Reimbursement API — Product Requirements Document

## 1. Introduction

Corporate travel reimbursement is a small clerical problem with a very large surface area: a per-diem table that turns over once a fiscal year, an IRS mileage rate that shifts annually, a flight policy that pegs reasonable airfare against a GSA-derived ceiling, a rental-car program whose Collision Damage Waiver economics flip depending on which state the traveler lands in, and a chain of human approvers whose job is to catch the cases the policy engine deliberately leaves to judgement. Each of these pieces is unremarkable on its own. They become hard the moment they intersect — a flight booked before the trip is approved, a meal expensed on a day a rental car was also driven, a high-cost destination that pulls an otherwise routine over-limit dinner into a three-tier approval chain.

This document specifies the Travel & Expense Reimbursement (T&E) backend that mediates those intersections. The system covers the complete lifecycle from trip request, manager pre-authorization, virtual card issuance, in-trip expensing with receipt OCR, an out-of-policy approval chain that can escalate one or two hops depending on amount and locality, all the way through to final disbursement. Two operational characteristics shape the design throughout. First, monetary derivations are computed twice — once provisionally at submission, again finally at approval — and the per-diem rate that drives them is **pinned** onto the trip at manager approval so that a subsequent administrative edit to the rate table cannot retroactively alter the reimbursable amount. Second, every approval, claim, and disbursement is subject to **segregation of duties**: the person travelling can never be the person approving their own spend.

The reader is asked to keep two mental models in mind throughout. Money flows are denominated in **integer cents**; there are no floating-point amounts anywhere on the wire. And expense-line state is two-dimensional: a `policy_status` axis evaluates the line against the policy engine, while an independent `ocr_status` axis evaluates the receipt against what the traveler claimed — the two axes evolve separately and only converge at report submission and final approval.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, a UUID that identifies the calling principal, and `X-User-Role`, a string identifying the principal's functional role. When either header is missing, empty, or `X-User-ID` is not a well-formed UUID, the request is rejected with `ERR_MISSING_AUTH`. When `X-User-Role` does not match a known role, or when the supplied `X-User-ID` does not resolve to an `Employee` carrying that role, the request is rejected with `ERR_INVALID_ROLE`. Authorization on individual endpoints uses the role catalogue below; an authenticated principal whose role is not on the endpoint's authorized list receives `ERR_INVALID_ROLE` as well.

Five roles are recognized, spelled exactly as shown: `TRAVELER`, `MANAGER`, `FINANCE_REVIEWER`, `OOP_APPROVER`, and `ADMIN`. The first four are entity-backed: when `X-User-Role` is any of `TRAVELER`, `MANAGER`, `FINANCE_REVIEWER`, or `OOP_APPROVER`, the `X-User-ID` value is the `id` of the acting `Employee`, and any ownership check on a resource that references an `Employee` (for example, a `Trip` referencing `traveler_id`, an `OutOfPolicyApproval` referencing `requester_employee_id`, or a `Receipt` referencing `uploader_employee_id`) compares that foreign-key field to `X-User-ID`. When `X-User-Role` is `ADMIN`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as part of audit context) but does not compare it to any entity's `id`.

The `TRAVELER` is the employee who travels and submits expense reports; the `MANAGER` is the direct manager of one or more travelers and acts as the L1 approver in the out-of-policy chain; the `FINANCE_REVIEWER` reviews and disburses expense reports and acts as the L2 approver; the `OOP_APPROVER` is the senior signatory who handles final-escalation cases (high-cost localities or large amounts); the `ADMIN` manages employees, per-diem rate rows, and the test-only logical clock.

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

All list endpoints accept two pagination query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, may not be less than 1, and may not exceed 100; `offset` defaults to 0 and may not be negative. List endpoints return results sorted by `created_at` in ascending order, and the response `meta` block carries the four pagination keys `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the count of records matching the filter before pagination is applied; `has_more` is true when `offset + limit < total_count`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Most resources carry four common fields. `id` is a server-minted UUID with no type prefix, returned as a plain string. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set at resource creation and never changes thereafter, while `updated_at` is refreshed on every mutation that alters any persisted field. `version` is an integer that begins at 1 on creation and increments by 1 on every mutation. The `PerDiemRate` and `Receipt` entities are exceptions — they carry only `id` and `created_at`; neither `updated_at` nor `version` is present on those two resources.

The `version` field powers optimistic concurrency control on every `PATCH` endpoint. When the client supplies a `version` value in the request body, the server compares it to the current persisted `version` of the resource; on mismatch the request is rejected with `ERR_STALE_VERSION`. When the client omits `version` from the request body, the OCC check is skipped and the mutation proceeds against whatever the current state happens to be. On every successful mutation, `version` is incremented by 1 and `updated_at` is refreshed to the current server timestamp.

### 2.5. Nested-Resource Path Resolution

Several endpoints embed resource identifiers in their URL paths — for example, expense lines hang off a report (`/expense-reports/{report_id}/lines`) and various transitions take a single resource id (`/trips/{id}/approve`, `/expense-lines/{id}/attach-receipt`). Path parameter resolution proceeds left-to-right: the outer path parameter is verified first, and only after it resolves to an existing resource does the server attempt to resolve the next segment. A miss at any segment yields `ERR_NOT_FOUND`. Foreign-key references in the request body (for example `receipt_id`, `virtual_card_id`, `manager_id`, `expense_line_id`, `trip_id`) are resolved after path resolution; a body-level FK that fails to resolve produces `ERR_REFERENCE_NOT_FOUND`.

### 2.6. Monetary Precision and Cent-Based Math

Every monetary amount on the wire is an **integer count of cents** — `amount_claimed_cents`, `amount_reimbursable_cents`, `lodging_cap_cents`, `mie_cap_cents`, `merchant_total_cents`, `credit_limit_cents`, `authorized_amount_cents`, `total_claimed_cents`, `total_reimbursable_cents`, and `estimated_budget_cents` are all integers. When a calculation produces a fractional cent intermediate (for example, multiplying a meal-share fraction against an `mie_cap_cents`), the intermediate is rounded **half-up** to the nearest whole cent before being used downstream. The trip budget rolls up nights and M&IE days as integer cents; the meal itemizer rounds the share-fraction product half-up; the mileage calculator rounds *each leg* of the mileage formula half-up at its own cent boundary and then sums the rounded leg amounts (per-leg-round-then-sum), which is not the same value as summing the unrounded products and rounding once. The report totals roll-up performs no rounding of its own — it sums already-rounded line amounts.

### 2.7. Validation Priority and Ordering

When a single request fails more than one rule, validations are applied in a strict priority order so that the returned `error_id` is deterministic. The order is: (1) presence and shape of the auth headers, returning `ERR_MISSING_AUTH`; (2) role recognition and entity binding, returning `ERR_INVALID_ROLE`; (3) existence of path-parameter resources, evaluated left-to-right, returning `ERR_NOT_FOUND`; (4) existence of body-referenced foreign keys, returning `ERR_REFERENCE_NOT_FOUND`; (5) the resource being in a state that permits the requested transition, returning `ERR_INVALID_STATE`; (6) cross-entity state preconditions such as a parent trip being in `APPROVED` or `COMPLETED` for report submission, or in `APPROVED` for virtual card issuance, returning `ERR_CROSS_ENTITY_STATE`; (7) segregation of duties on approval and disbursement endpoints, returning `ERR_SEGREGATION_OF_DUTIES`; (8) a receipt not already bound to another line, returning `ERR_RECEIPT_ALREADY_USED`; (9) a virtual card whose `trip_id` matches the report's parent trip, returning `ERR_CARD_TRIP_MISMATCH`; (10) the `expense_date` falling within the trip window inclusive of the start and end dates, returning `ERR_EXPENSE_OUTSIDE_TRIP_WINDOW`; (11) a per-diem rate covering the destination on the relevant date, returning `ERR_PER_DIEM_UNAVAILABLE`; (12) a receipt being attached when the category or amount demands one, returning `ERR_RECEIPT_REQUIRED`; (13) the category-specific required fields being populated, returning `ERR_CATEGORY_FIELD_MISSING`; (14) the card credit limit at issuance not exceeding the trip budget, returning `ERR_CARD_LIMIT_EXCEEDS_BUDGET`; (15) a card charge not pushing authorized totals above the credit limit, returning `ERR_CARD_LIMIT_EXCEEDED`; (16) the OOP step being invoked by the correct role, returning `ERR_OOP_WRONG_APPROVER_ROLE`; (17) the OOP final approver not being the same person as the L1 approver, returning `ERR_OOP_DUPLICATE_APPROVER`; and (18) the optimistic-concurrency `version` check, returning `ERR_STALE_VERSION`. Any input shape problem not otherwise covered (a missing required body field, a malformed enum value, a non-integer cent amount) is reported as `ERR_VALIDATION`.

### 2.8. Pinning, Replay, and the Provisional/Final Calculation Pair

Several monetary calculations run twice in the lifetime of a single line. They run **provisionally** during line creation, line edit, and trip submission — resolving the applicable `PerDiemRate` against whatever rate row is live at the relevant date — and they run **finally** at report approval, replaying against the `PerDiemRate` whose `id` is recorded in `pinned_per_diem_rate_id` on the trip. The pin is set onto the trip when the manager approves the trip, capturing the rate that was live at the trip's `start_date` at that moment, and is the system's defence against an administrator editing the per-diem table between trip approval and report disbursement. When the rate row has not been edited between trip approval and report approval, the provisional and final amounts are identical; when it has been edited, the final variant uses the **pinned** values and the two diverge. The trip budget estimate, meal itemization, and flight variance calculations all participate in this provisional/final pairing.

### 2.9. Cascading State Effects and Atomicity

Every request is atomic: the request's primary state transition and every cascade it triggers either all succeed and are persisted together, or the entire request is rolled back. Whenever an entity is mutated, its `updated_at` is refreshed and its `version` is incremented by 1; entities touched by cascade hops are likewise version-bumped and timestamp-refreshed. A trip rejection, for example, transitions the trip itself, propagates to any pending virtual cards, and from there propagates to any expense reports already opened on that trip — each step bumps the affected entity's `version`. Cascade rules are spelled out alongside the transitions that trigger them in §3.

### 2.10. Concurrency and Conflict Resolution

When two clients race on a mutation that the data model can only accept once, the system serializes the writes and the loser receives a deterministic conflict error. Two finance reviewers racing to `/claim` the same `SUBMITTED` report serialize on the report's `reviewer_id` field — the first writer sets `reviewer_id`, transitions the report to `IN_REVIEW`, and the loser receives `ERR_REPORT_ALREADY_CLAIMED`. Two travelers racing to attach the same receipt to two different lines serialize on the receipt's `used_by_line_id` field — the first writer binds the receipt, the loser receives `ERR_RECEIPT_ALREADY_USED`. Two approvers racing approve-vs-deny on the same out-of-policy approval serialize on `chain_level` — exactly one terminal transition wins, the loser receives `ERR_INVALID_STATE`. Two simultaneous charges against the same virtual card where the second would breach the credit limit serialize on the card's `id` and check `authorized_amount_cents` under lock — the first authorization succeeds, the loser receives `ERR_CARD_LIMIT_EXCEEDED`. Two simultaneous `/disburse` calls on an `APPROVED` report serialize on the report's `status` — one advances the report to `REIMBURSED`, the loser receives `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. The Trip Request

A trip begins life when a traveler creates a `Trip` resource, supplying the `traveler_id` (which must reference an `Employee` whose `role` is `TRAVELER`), a free-form `purpose` between 1 and 500 characters, the `origin_city` and `origin_state` (a two-letter US state code), the `destination_city` and `destination_state`, and the `start_date` and `end_date` (UTC midnight semantics; `end_date` must be greater than or equal to `start_date`). The trip is born in `DRAFT` with its `status` field set accordingly and with `estimated_budget_cents` initialized to zero and `pinned_per_diem_rate_id` and `approved_at` both null.

While in `DRAFT`, the traveler may edit the trip's `purpose`, `origin_city`, `origin_state`, `destination_city`, `destination_state`, `start_date`, and `end_date` as many times as needed. When the traveler is ready, submitting the trip advances `status` from `DRAFT` to `SUBMITTED`. Submission is only valid when the traveler issuing the request owns the trip (the trip's `traveler_id` equals the calling `X-User-ID`), when the date ordering still holds, and when the destination resolves to at least one `PerDiemRate` row whose `[effective_from, effective_to)` window covers the trip's `start_date` — the window is **inclusive on the left** of `effective_from` and **exclusive on the right** of `effective_to`. If no such rate row exists, submission fails with `ERR_PER_DIEM_UNAVAILABLE`. As a side effect of successful submission, the server computes the provisional `estimated_budget_cents` (see §3.7).

A submitted trip is then routed to the traveler's manager. The manager — whose `Employee.id` must equal the traveler's `manager_id` — may take one of three actions. Approval advances `status` from `SUBMITTED` to `APPROVED`, pins `pinned_per_diem_rate_id` to the `id` of the `PerDiemRate` that was resolved at submission (defending against subsequent administrative edits), and stamps `approved_at` with the current server time. Approval also requires `estimated_budget_cents` to be strictly greater than zero. Rejection advances `status` from `SUBMITTED` to `REJECTED` (a terminal state), accepts an optional `reason` field, and triggers a two-hop cascade: any `VirtualCard` for this trip with `status` equal to `REQUESTED` transitions automatically to `CLOSED`, and any `ExpenseReport` already opened on this trip transitions automatically to `REJECTED` (because a closed funding source on a non-approved trip invalidates the report). Requesting changes advances `status` from `SUBMITTED` to `CHANGES_REQUESTED`, accepts optional `notes`, and triggers no further cascade.

A `CHANGES_REQUESTED` trip cycles back to `DRAFT` the next time the traveler edits the trip; the transition clears `estimated_budget_cents` back to zero and clears `pinned_per_diem_rate_id` back to null, after which the traveler may revise and re-submit.

Once `APPROVED`, the trip can take two further paths. The traveler may complete the trip — provided the current logical date is on or after `end_date` — which advances `status` to `COMPLETED` (terminal). Completion is gated on the server's logical clock, which an admin-only test-driving capability can advance to a supplied `to` instant. Completion triggers a single cascade: every `VirtualCard` belonging to the trip with `status` equal to `ACTIVE` is automatically transitioned to `LOCKED` with `locked_reason` set to `trip_completed`, preventing post-trip charges. Alternatively, the traveler may cancel the trip — provided no `ExpenseReport` on this trip has a `status` other than `DRAFT` — which advances `status` to `CANCELLED` (terminal) and triggers a cascade that closes every `VirtualCard` belonging to the trip whose `status` is in the set `REQUESTED`, `ISSUED`, or `ACTIVE`.

### 3.2. Virtual Card Lifecycle and Card Funding Discipline

Once a trip has reached `APPROVED`, the traveler can request a `VirtualCard` for it by supplying the `trip_id` and the desired `credit_limit_cents`. The card's `credit_limit_cents` must be non-negative and, at issuance time, must not exceed the trip's `estimated_budget_cents` — if it does, the request fails with `ERR_CARD_LIMIT_EXCEEDS_BUDGET`. The card is born in `REQUESTED` with `authorized_amount_cents` initialized to zero, `card_last4` and `locked_reason` unset.

A finance reviewer then issues the card, advancing `status` from `REQUESTED` to `ISSUED`. Issuance requires the parent trip to still be in `APPROVED` (otherwise `ERR_CROSS_ENTITY_STATE`) and re-checks the credit-limit constraint against the trip's budget. As a side effect of issuance, the server mints `card_last4` — a four-digit string derived deterministically from the card's `id`. The traveler then activates the card, advancing `status` from `ISSUED` to `ACTIVE`, after which the card may be charged against expense lines. Finance may at any point lock an `ACTIVE` card (advancing `status` to `LOCKED` and capturing the supplied `locked_reason` from the request body), unlock it again (advancing back to `ACTIVE` and clearing `locked_reason`, but only when the parent trip's `status` is neither `COMPLETED` nor `CANCELLED`), or close it (advancing `status` from `ACTIVE` to `CLOSED`, a terminal state). The lock-and-unlock pair forms an explicit cycle: a card may move between `ACTIVE` and `LOCKED` any number of times before being closed.

System-driven transitions also drive cards into terminal states. When a parent trip is rejected or cancelled, any `REQUESTED` card on that trip transitions automatically to `CLOSED` (this is the cascade hop fired by trip rejection and trip cancellation). When a parent trip is completed, every `ACTIVE` card transitions to `LOCKED` with `locked_reason` set to `trip_completed`.

The card's `authorized_amount_cents` is a running ledger of authorized charges. Every time an expense line is created or edited with a non-null `virtual_card_id`, the line's reimbursable amount is added to that card's `authorized_amount_cents` — and if that running total would exceed `credit_limit_cents`, the request is rejected with `ERR_CARD_LIMIT_EXCEEDED`. Two concurrent charges that would individually fit but together breach the limit serialize on the card; one wins, the other receives `ERR_CARD_LIMIT_EXCEEDED`. When the report is later rejected and child lines transition to `VOIDED`, each voided line whose `virtual_card_id` is non-null deauthorizes — the card's `authorized_amount_cents` is decremented by the line's `amount_reimbursable_cents`.

### 3.3. The Expense Report and Its Two-Dimensional Lines

An `ExpenseReport` is opened by the traveler against a specific trip. The trip identifier (`trip_id`) is supplied in the create payload. A new report is born in `DRAFT` with `total_claimed_cents`, `total_reimbursable_cents`, and `policy_violation_count` all at zero, and with `reviewer_id`, `submitted_at`, `approved_at`, and `reimbursed_at` all null.

Inside a draft report, the traveler adds individual `ExpenseLine` rows. Every line carries a parent `report_id`, an expense `category` from the enumeration `FLIGHT`, `LODGING`, `RENTAL_CAR`, `MEAL`, `MILEAGE`, or `OTHER`, and an `expense_date` (UTC midnight semantics) that must fall within the trip's `[start_date, end_date]` window inclusive on both ends — otherwise the line is rejected with `ERR_EXPENSE_OUTSIDE_TRIP_WINDOW`. For categories other than `MILEAGE`, the traveler supplies `amount_claimed_cents` directly; for `MILEAGE`, `amount_claimed_cents` must be omitted on create and the server computes it from `miles_driven`. Polymorphic per-category fields complete the picture: `MILEAGE` requires `miles_driven` (a decimal with one fractional digit); `RENTAL_CAR` requires `rental_days` (an integer of at least 1) and accepts the `cdw_purchased` boolean; `MEAL` requires `meal_type` (one of `BREAKFAST`, `LUNCH`, `DINNER`, or `INCIDENTAL`) and accepts the `meal_was_provided` boolean; both `LODGING` and `MEAL` require a `per_diem_method` of either `ACTUAL` (itemized claim) or `PER_DIEM` (cap-based), although `MEAL` waives the requirement when `meal_was_provided` is true. A missing category-specific field yields `ERR_CATEGORY_FIELD_MISSING`.

A line carries two parallel state dimensions that evolve independently. The first is `policy_status` — initialized to `PENDING_EVAL` on create and resolved inline by the category-specific calculation to either `IN_POLICY` (when the post-calculation claim is at or below the applicable cap) or `OUT_OF_POLICY` (when it exceeds the cap). Transitioning a line into `OUT_OF_POLICY` increments the parent report's `policy_violation_count` by 1. A line that has become `OUT_OF_POLICY` can subsequently transition to either `OOP_APPROVED` or `OOP_DENIED` as a system-driven side effect of the out-of-policy approval chain reaching its terminal `FINAL_APPROVED` or `DENIED` state. When an `OUT_OF_POLICY` line transitions to `OOP_APPROVED`, the system sets `amount_reimbursable_cents` equal to `amount_claimed_cents`, decrements the parent report's `policy_violation_count` by 1, and adds the difference between the new and prior reimbursable values to the parent's `total_reimbursable_cents`. When the line transitions to `OOP_DENIED` instead, `amount_reimbursable_cents` is set to the capped amount that the category's calculation would have produced.

The second dimension is `ocr_status`, which is initialized to `NO_RECEIPT` and advances independently of `policy_status`. Attaching a receipt advances `ocr_status` from `NO_RECEIPT` to `PENDING_OCR` (and sets the receipt's `used_by_line_id` to this line's `id`, irrevocably; a receipt may not be rebound to a different line). The system then resolves `PENDING_OCR` against the receipt: when the receipt's `merchant_total_cents` equals the line's `amount_claimed_cents` and `ocr_confidence` is at least 0.80, the line advances to `OCR_VERIFIED`. Otherwise it advances to `OCR_MISMATCH`, with one carve-out: for meal lines, when the absolute difference between `merchant_total_cents` and `amount_claimed_cents` is at most 200 cents (two dollars) and `ocr_confidence` is at least 0.60, the line is auto-set to `OCR_WAIVED` instead. A finance reviewer can additionally waive an existing `OCR_MISMATCH` on a line whose parent report has `status` equal to `IN_REVIEW`, advancing `ocr_status` to `OCR_WAIVED` and accepting an optional `waiver_note`.

A line's top-level `line_status` rolls up the two dimensions. It starts at `ACTIVE` and stays there throughout normal authoring. It transitions to `VOIDED` as a system-driven cascade when the parent report is rejected — and that void, in turn, deauthorizes any virtual card the line was charged against by subtracting `amount_reimbursable_cents` from the card's `authorized_amount_cents`. It transitions to `REIMBURSED` as a system-driven cascade when the parent report is disbursed.

Every line creation or edit triggers two rollups on the parent report. `total_claimed_cents` is recomputed as the sum of `amount_claimed_cents` across all child lines whose `line_status` is not `VOIDED`; `total_reimbursable_cents` is recomputed as the sum of `amount_reimbursable_cents` across the same set; and `policy_violation_count` is recomputed as the count of child lines whose `policy_status` equals `OUT_OF_POLICY`. The rollup performs no rounding — it merely sums already-rounded integer cent values.

### 3.4. Receipts, OCR, and the Receipt Requirement Rule

Receipts are uploaded by the traveler, who supplies `merchant_name`, `merchant_total_cents`, `ocr_extracted_date`, and `ocr_confidence` (a number in the closed interval from 0.00 to 1.00) at upload time. The server records the supplied `uploader_employee_id` from the caller's `X-User-ID`. A receipt is required when the line's category is `LODGING`, `RENTAL_CAR`, or `FLIGHT`, **or** when `amount_claimed_cents` is strictly greater than 7500 cents (which is seventy-five dollars). When a line that demands a receipt is created or submitted without one, the request is rejected with `ERR_RECEIPT_REQUIRED`.

The receipt's `used_by_line_id` is the binding marker between a receipt and its line. It is null until first attached and, once set, may not be set to a different line; an attempt to bind a receipt that is already in use is rejected with `ERR_RECEIPT_ALREADY_USED`. When two travelers race to attach the same receipt, exactly one binding wins and the loser receives the same error code. Reports cannot be submitted while any `LODGING`, `RENTAL_CAR`, or `FLIGHT` line still lacks a bound receipt — submission requires every such line to be in one of `OCR_VERIFIED`, `OCR_MISMATCH`, or `OCR_WAIVED`.

### 3.5. Out-of-Policy Approvals and the Approval Chain

When a line is found to be `OUT_OF_POLICY`, the traveler may open an `OutOfPolicyApproval` by supplying the `expense_line_id` and a `justification` between 10 and 1000 characters. The `requester_employee_id` is the traveler's `Employee.id`. At creation, the system computes `requires_final_escalation` — set to true if and only if the bound line's `amount_claimed_cents` is strictly greater than 100000 cents (which is one thousand dollars) **or** the destination's `PerDiemRate` has `is_high_cost_locality` equal to true. The approval is born in `AWAITING_L1` with `l1_approver_id`, `l2_approver_id`, and `final_approver_id` all null.

The chain runs in steps, each step requiring a specific role. The L1 step (`AWAITING_L1` advancing to `AWAITING_L2`) must be invoked by a `MANAGER` whose `Employee.id` equals the traveler's `manager_id`, and the manager must not themselves be the traveler — segregation of duties applies. As a side effect, `l1_approver_id` is set to `X-User-ID`. A wrong-role invocation yields `ERR_OOP_WRONG_APPROVER_ROLE`; an attempted self-approval yields `ERR_SEGREGATION_OF_DUTIES`.

The L2 step is invoked by a `FINANCE_REVIEWER` who is not the traveler. Its destination depends on `requires_final_escalation`: when escalation is required, the chain advances from `AWAITING_L2` to `AWAITING_FINAL`; when escalation is not required, the chain advances directly from `AWAITING_L2` to `FINAL_APPROVED`, and the bound line's `policy_status` is transitioned by the system to `OOP_APPROVED` as a cascade. In both branches, `l2_approver_id` is set to `X-User-ID`. A wrong-role invocation yields `ERR_OOP_WRONG_APPROVER_ROLE`.

The final step is invoked by an `OOP_APPROVER`, advancing the chain from `AWAITING_FINAL` to `FINAL_APPROVED`. The acting approver must not be the traveler, and must not be the same person who acted at L1 — the latter check returns `ERR_OOP_DUPLICATE_APPROVER`, preventing a manager who has both approver roles from rubber-stamping their own L1 decision. As a side effect, `final_approver_id` is set to `X-User-ID` and the bound line's `policy_status` cascades to `OOP_APPROVED`.

At any chain level, the current approver may deny the request: a `MANAGER` may deny from `AWAITING_L1`, a `FINANCE_REVIEWER` may deny from `AWAITING_L2`, and an `OOP_APPROVER` may deny from `AWAITING_FINAL`. Denial advances `chain_level` to `DENIED` (terminal), accepts an optional `reason`, and cascades the bound line's `policy_status` to `OOP_DENIED`.

When the same approval races approve-vs-deny simultaneously, the two writes serialize on `chain_level` and exactly one terminal transition wins; the loser receives `ERR_INVALID_STATE`.

### 3.6. Report Submission, Review, and Disbursement

Once the traveler is satisfied with the report's lines, they submit it. Submission requires the parent trip to be in `APPROVED` or `COMPLETED` (otherwise `ERR_CROSS_ENTITY_STATE`), requires at least one child line with `line_status` equal to `ACTIVE`, and requires every line in the receipt-mandatory categories (`LODGING`, `RENTAL_CAR`, `FLIGHT`) to have a bound receipt whose `ocr_status` is in `OCR_VERIFIED`, `OCR_MISMATCH`, or `OCR_WAIVED`. As a side effect of submission, `submitted_at` is set to the current server time and `total_claimed_cents`, `total_reimbursable_cents`, and `policy_violation_count` are recomputed.

A finance reviewer then claims the report, advancing `status` from `SUBMITTED` to `IN_REVIEW` and setting `reviewer_id` to the calling `X-User-ID`. The claim races serialize on `reviewer_id` — the first writer succeeds, the loser receives `ERR_REPORT_ALREADY_CLAIMED`.

From `IN_REVIEW`, the claiming reviewer may take one of three actions. Approval advances `status` from `IN_REVIEW` to `APPROVED`, requires that `policy_violation_count` equals zero **or** that every `OUT_OF_POLICY` line has a resolved `OutOfPolicyApproval` in `FINAL_APPROVED`, requires the acting `reviewer_id` to equal the calling `X-User-ID`, requires the acting employee not to be the trip's traveler (segregation of duties), and as side effects sets `approved_at` to the current server time and recomputes `total_reimbursable_cents` using the **final** variant of each calculation (replaying meal itemization and flight variance against `pinned_per_diem_rate_id`). Rejection advances `status` from `IN_REVIEW` to `REJECTED`, requires the acting reviewer to be the claiming reviewer, accepts an optional `reason`, and triggers a three-hop cascade: every child line with `line_status` equal to `ACTIVE` transitions to `VOIDED`; each voided line with a non-null `virtual_card_id` deauthorizes its card by decrementing `authorized_amount_cents` by the line's `amount_reimbursable_cents`; and any `OutOfPolicyApproval` bound to a now-voided line transitions to `DENIED`. Requesting changes advances `status` from `IN_REVIEW` to `CHANGES_REQUESTED`, requires the acting reviewer to be the claiming reviewer, and accepts optional `notes`. A `CHANGES_REQUESTED` report cycles back to `DRAFT` the next time the traveler edits the report or adds a line; the cycle-back clears `reviewer_id`.

An `APPROVED` report can finally be disbursed, advancing `status` from `APPROVED` to `REIMBURSED` (terminal). Disbursement requires `approved_at` to be non-null and the acting employee to not be the traveler. As side effects, `reimbursed_at` is set to the current server time and every child line with `line_status` equal to `ACTIVE` transitions to `REIMBURSED`. Two concurrent disburse attempts serialize on `status`; one wins, the loser receives `ERR_INVALID_STATE`.

### 3.7. The Trip Budget and Per-Diem Math

The trip budget is computed at submission (provisionally) and at report approval (finally) by aggregating two components: lodging and M&IE (Meals & Incidentals). The number of **nights** is the difference between `end_date` and `start_date` expressed in whole days; the number of **M&IE days** is the number of nights plus one (per the GSA convention that travel days are included). The applicable rate is resolved by looking up the `PerDiemRate` row whose city and state match the trip's `destination_city` and `destination_state` (case-insensitively on city) and whose `[effective_from, effective_to)` window covers the trip's `start_date`; the lookup is **live** in the provisional variant and **pinned** via `pinned_per_diem_rate_id` in the final variant.

The lodging budget is the resolved rate's `lodging_cap_cents` multiplied by the number of nights, in integer cents. The M&IE budget follows the GSA "first-and-last-day rule": the first and last day of travel each receive 75% of the `mie_cap_cents`, while every full middle day receives the full `mie_cap_cents`. When the trip is a single M&IE day (one M&IE day total — that is, zero nights), the M&IE budget is the `mie_cap_cents` multiplied by 0.75 and rounded half-up to the nearest cent. When the trip spans two or more M&IE days, the M&IE budget is twice (the `mie_cap_cents` multiplied by 0.75 and rounded half-up), plus the full `mie_cap_cents` multiplied by the count of middle days (M&IE days minus 2). The lodging and M&IE budgets are summed to produce `estimated_budget_cents`. The first-and-last-day fraction (0.75) is the only constant baked into this calculation.

The provisional variant — fired at trip submission — uses the rate that is live at `start_date` at submission time and stores the result on `estimated_budget_cents` without pinning the rate. The final variant — fired at report approval — resolves the rate via `Trip.pinned_per_diem_rate_id` (frozen at trip approval), so if the rate row has been edited between trip approval and report approval, the two variants diverge even when the trip's inputs are identical. The two variants are otherwise identical in formula and rounding.

### 3.8. Meal Itemization

A meal line's reimbursable amount depends on whether the meal was provided to the traveler, on the meal type, and on the per-diem method. When `meal_was_provided` is true, the line's `amount_reimbursable_cents` is forced to zero and `policy_status` is auto-set to `IN_POLICY` (the "provided meal deduction"). Otherwise the server resolves the destination's `PerDiemRate` for the line's `expense_date` (live in the provisional variant; via `pinned_per_diem_rate_id` in the final variant at report approval), and computes a per-meal cap by multiplying `mie_cap_cents` against the type-specific meal share and rounding half-up to integer cents: breakfast receives a share of 0.25, lunch 0.30, dinner 0.45, and incidental 0.05. The four shares sum to 1.00 and partition the daily M&IE cap.

When `per_diem_method` equals `PER_DIEM`, the line is reimbursed at exactly that per-meal cap. When `per_diem_method` equals `ACTUAL`, the line is reimbursed at the lesser of `amount_claimed_cents` and the per-meal cap — and if `amount_claimed_cents` is strictly greater than the per-meal cap, the line is additionally transitioned to `policy_status` equal to `OUT_OF_POLICY` (capped at the per-meal cap pending OOP approval). When OOP approval is subsequently granted, the line's `amount_reimbursable_cents` is set to `amount_claimed_cents` per the cascade described in §3.3.

The meal calculation is one of those that runs twice: provisionally on line create or edit (resolving the live rate) and finally at report approval (resolving via `pinned_per_diem_rate_id`).

### 3.9. Mileage Reimbursement and the Personal-Car Overlap

A mileage line carries `miles_driven` instead of a directly-claimed amount; the server computes `amount_reimbursable_cents` and copies it into `amount_claimed_cents` as well. The IRS standard business rate baked into this calculation is 67 cents per mile. The calculation uses a per-leg-round-then-sum convention: each leg's cents value is computed (miles times rate), rounded half-up to integer cents, and the rounded values are summed. This is intentional — summing the unrounded products and rounding once produces a different value, and the calculation pins the per-leg order.

A second rule kicks in when the same report carries a `RENTAL_CAR` line for the same `expense_date` (and that rental line is not voided): the mileage line is considered a **personal-car overlap** with the rental. The first 30 round-trip miles are reimbursed at the standard business rate of 67 cents per mile; every mile beyond the 30-mile threshold is reimbursed at the deeply discounted personal-overlap rate of 21 cents per mile, to discourage double-dipping between rental-car and mileage reimbursement. Concretely, when overlap applies and `miles_driven` is strictly greater than 30, the reimbursable amount is (the 30-mile threshold multiplied by 67 cents per mile, rounded half-up) plus ((`miles_driven` minus 30) multiplied by 21 cents per mile, rounded half-up). When `miles_driven` is at most 30 — or when there is no same-date rental line — the full mileage is at 67 cents per mile, rounded half-up.

The mileage line's `policy_status` follows the same rule as the other categories: the post-calculation amount is compared to the applicable cap and the line lands in `IN_POLICY` when at or below, `OUT_OF_POLICY` when above. Because the mileage formula already enforces its own ceiling (the personal-overlap discount **is** the cap), the standalone mileage line is effectively always within policy unless an external constraint flags it.

### 3.10. Rental Car and the CDW Geography Rule

A rental car line's reimbursable amount is computed from the integer `rental_days` field and a base daily cap of 6500 cents per day (sixty-five dollars per day). The base reimbursable amount is the lesser of `amount_claimed_cents` and (`rental_days` multiplied by 6500 cents).

Collision Damage Waiver (CDW) treatment depends on geography. When `cdw_purchased` is true and the trip's `destination_state` is **not** in the corporate-CDW-covered list — California (`CA`), Texas (`TX`), New York (`NY`), Florida (`FL`), and Washington (`WA`) — CDW is reimbursable up to a daily cap of 1500 cents per day (fifteen dollars per day). In that case, when `amount_claimed_cents` exceeds the base reimbursable amount, the excess is treated as the CDW component, capped at (`rental_days` multiplied by 1500 cents), and the total reimbursable becomes the base amount plus the capped CDW component. When the destination state **is** in the corporate-CDW list, the corporate insurance program covers CDW and the CDW component is non-reimbursable regardless of the `cdw_purchased` flag — the reimbursable amount is the base amount alone, even if the traveler paid for CDW.

When `cdw_purchased` is false, the reimbursable amount is simply the base amount with no CDW handling.

A rental line where the computed reimbursable exceeds the cap structure is flagged as `OUT_OF_POLICY`; otherwise it is `IN_POLICY`.

### 3.11. Flight Variance Against the Lowest Logical Fare

A flight line's reimbursable amount and policy status are determined by computing a **Lowest Logical Fare (LLF)** ceiling and comparing the claimed amount against it. The LLF for a given destination and date is the sum of that destination's `lodging_cap_cents` and `mie_cap_cents` for the `PerDiemRate` that covers the flight's `expense_date`. The **variance** is `amount_claimed_cents` minus that LLF.

When the variance is at most 10000 cents (one hundred dollars), the line is `IN_POLICY` and `amount_reimbursable_cents` equals `amount_claimed_cents` — the traveler is reimbursed the full claim. When the variance is strictly greater than 10000 cents, the line is `OUT_OF_POLICY` and `amount_reimbursable_cents` is capped at the LLF (the lodging plus M&IE cap sum), pending OOP approval; if OOP approval is granted, the cascade described in §3.3 lifts `amount_reimbursable_cents` back to `amount_claimed_cents`.

This calculation runs in two variants. The forward-looking variant fires during line creation and edit, pinning the variance against the `PerDiemRate` that is live at the flight's `expense_date`; it is never updated by later rate edits. The chronological variant fires at report approval and replays the variance against `Trip.pinned_per_diem_rate_id`, which was frozen at trip approval — and **not** at the flight line's `expense_date`. The two variants diverge whenever the line's `expense_date` falls in a different rate window than the trip's `start_date`, because the pinned rate may differ from the date-local rate that the forward-looking variant resolved.

### 3.12. Reference Data and Administrative Capabilities

Per-diem rates are loaded and edited by an `ADMIN` operator, whose create payload carries `city`, `state`, `effective_from`, `effective_to`, `lodging_cap_cents`, `mie_cap_cents`, and `is_high_cost_locality`. Per-diem rate rows do not carry `updated_at` or `version` — they carry only `id` and `created_at` — so administrative re-loads of the rate table do not collide with OCC; the pinning mechanism on the trip (`pinned_per_diem_rate_id`) is the protection against the rate row changing under an approved trip.

Employees are created by an `ADMIN` operator who supplies `full_name`, `email` (globally unique, compared case-insensitively), `role` (one of `TRAVELER`, `MANAGER`, `FINANCE_REVIEWER`, `OOP_APPROVER`, or `ADMIN`), an optional `manager_id` (required for `TRAVELER`, must be null for `ADMIN`), `cost_center`, and `home_address_state`. The `home_address_state` serves as the default origin for per-diem boundary checks.

An admin-only test-driving capability advances the server's logical clock to a supplied `to` instant. All subsequent calls to the server's internal `now()` return the advanced value; this is the mechanism by which the time-gated trip-completion transition (`APPROVED` advancing to `COMPLETED`) can be exercised against a future `end_date`.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in the response body. All other successful endpoints — retrievals, lifecycle transitions, edits, and disbursements — return HTTP 200. Validation failures, conflicts, and authorization failures use the standard error envelope and the priority order described in §2.7.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /trips | Create a Trip in DRAFT state. | TRAVELER |
| GET | /trips | List trips, filtered by `traveler_id`, `status`, and the trip-start date range `start_date_from` (inclusive) and `start_date_to` (inclusive). | TRAVELER, MANAGER, FINANCE_REVIEWER, ADMIN |
| GET | /trips/{id} | Retrieve a Trip. | TRAVELER, MANAGER, FINANCE_REVIEWER, ADMIN |
| PATCH | /trips/{id} | Edit a Trip while in DRAFT or CHANGES_REQUESTED. | TRAVELER |
| POST | /trips/{id}/submit | Submit a DRAFT trip for manager approval. | TRAVELER |
| POST | /trips/{id}/approve | Manager approves a submitted trip. | MANAGER |
| POST | /trips/{id}/reject | Manager rejects a submitted trip (terminal). | MANAGER |
| POST | /trips/{id}/request-changes | Manager sends a trip back to the traveler for revisions. | MANAGER |
| POST | /trips/{id}/complete | Traveler marks an approved trip completed after `end_date`. | TRAVELER |
| POST | /trips/{id}/cancel | Traveler cancels an approved trip before travel begins. | TRAVELER |
| POST | /virtual-cards | Request a VirtualCard for an APPROVED trip. | TRAVELER |
| POST | /virtual-cards/{id}/issue | Finance issues a REQUESTED card. | FINANCE_REVIEWER |
| POST | /virtual-cards/{id}/activate | Traveler activates an ISSUED card. | TRAVELER |
| POST | /virtual-cards/{id}/lock | Finance locks an ACTIVE card. | FINANCE_REVIEWER |
| POST | /virtual-cards/{id}/unlock | Finance unlocks a LOCKED card (cycle back to ACTIVE). | FINANCE_REVIEWER |
| POST | /virtual-cards/{id}/close | Finance closes a card (terminal). | FINANCE_REVIEWER |
| GET | /virtual-cards/{id} | Retrieve a virtual card. | TRAVELER, FINANCE_REVIEWER, ADMIN |
| POST | /expense-reports | Create an ExpenseReport bound to a trip. | TRAVELER |
| GET | /expense-reports | List expense reports; filterable by `traveler_id`, `status`, `trip_id`. | TRAVELER, FINANCE_REVIEWER, ADMIN |
| GET | /expense-reports/{id} | Retrieve an expense report. | TRAVELER, MANAGER, FINANCE_REVIEWER, ADMIN |
| POST | /expense-reports/{id}/submit | Submit a DRAFT report. | TRAVELER |
| POST | /expense-reports/{id}/claim | Finance reviewer claims a SUBMITTED report. | FINANCE_REVIEWER |
| POST | /expense-reports/{id}/approve | Reviewer approves an IN_REVIEW report. | FINANCE_REVIEWER |
| POST | /expense-reports/{id}/reject | Reviewer rejects an IN_REVIEW report. | FINANCE_REVIEWER |
| POST | /expense-reports/{id}/request-changes | Reviewer sends report back to traveler. | FINANCE_REVIEWER |
| POST | /expense-reports/{id}/disburse | Reviewer disburses APPROVED report (terminal). | FINANCE_REVIEWER |
| PATCH | /expense-reports/{id} | Edit a CHANGES_REQUESTED report (lightweight metadata edits). | TRAVELER |
| POST | /expense-reports/{report_id}/lines | Add a new expense line to a report. | TRAVELER |
| PATCH | /expense-lines/{id} | Edit a line in a DRAFT or CHANGES_REQUESTED report. | TRAVELER |
| GET | /expense-lines/{id} | Retrieve an expense line. | TRAVELER, MANAGER, FINANCE_REVIEWER, ADMIN |
| POST | /expense-lines/{id}/attach-receipt | Bind a Receipt to a line (drives `ocr_status`). | TRAVELER |
| POST | /expense-lines/{id}/waive-ocr | Finance waives an OCR_MISMATCH while report IN_REVIEW. | FINANCE_REVIEWER |
| POST | /receipts | Upload a receipt (caller supplies OCR fields directly). | TRAVELER |
| GET | /receipts/{id} | Retrieve a receipt. | TRAVELER, FINANCE_REVIEWER, ADMIN |
| POST | /oop-approvals | Open an OOP approval for an OUT_OF_POLICY line. | TRAVELER |
| GET | /oop-approvals/{id} | Retrieve an OOP approval. | TRAVELER, MANAGER, FINANCE_REVIEWER, OOP_APPROVER, ADMIN |
| POST | /oop-approvals/{id}/l1-approve | Manager step (AWAITING_L1 → AWAITING_L2). | MANAGER |
| POST | /oop-approvals/{id}/l2-approve | Finance step (AWAITING_L2 → AWAITING_FINAL or FINAL_APPROVED). | FINANCE_REVIEWER |
| POST | /oop-approvals/{id}/final-approve | OOP approver step (AWAITING_FINAL → FINAL_APPROVED). | OOP_APPROVER |
| POST | /oop-approvals/{id}/deny | Current approver denies at their chain level. | MANAGER, FINANCE_REVIEWER, OOP_APPROVER |
| POST | /per-diem-rates | Admin loads or edits a per-diem rate row. | ADMIN |
| GET | /per-diem-rates | List per-diem rates; filterable by `city`, `state`, `effective_on`. | TRAVELER, MANAGER, FINANCE_REVIEWER, OOP_APPROVER, ADMIN |
| POST | /employees | Admin creates an employee. | ADMIN |
| GET | /employees/{id} | Retrieve an employee. | TRAVELER, MANAGER, FINANCE_REVIEWER, OOP_APPROVER, ADMIN |
| POST | /_clock/advance | Test-driving clock advance (sets the server's logical now). | ADMIN |

## 5. Error Code Catalogue

| Error ID | HTTP Status |
|---|---|
| ERR_MISSING_AUTH | 401 |
| ERR_INVALID_ROLE | 401 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_CROSS_ENTITY_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_RECEIPT_ALREADY_USED | 409 |
| ERR_CARD_TRIP_MISMATCH | 422 |
| ERR_EXPENSE_OUTSIDE_TRIP_WINDOW | 422 |
| ERR_PER_DIEM_UNAVAILABLE | 422 |
| ERR_RECEIPT_REQUIRED | 422 |
| ERR_CATEGORY_FIELD_MISSING | 422 |
| ERR_CARD_LIMIT_EXCEEDS_BUDGET | 422 |
| ERR_CARD_LIMIT_EXCEEDED | 409 |
| ERR_OOP_WRONG_APPROVER_ROLE | 403 |
| ERR_OOP_DUPLICATE_APPROVER | 403 |
| ERR_STALE_VERSION | 409 |
| ERR_REPORT_ALREADY_CLAIMED | 409 |
| ERR_VALIDATION | 400 |
