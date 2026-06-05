# Travel Expense Reimbursement API — Product Requirements Document

## 1. Introduction

Corporate travel reimbursement sits at the intersection of two pressures that rarely cooperate: employees want their out-of-pocket and card-funded costs returned quickly, while finance and audit need every dollar to survive a regulatory cap before it leaves the building. This API operationalizes a federal-style Travel & Expense (T&E) program in which General Services Administration (GSA) per-diem ceilings, airfare cabin policy, rental-car Collision Damage Waiver (CDW) limits, and a personal-vehicle mileage rate are all enforced automatically, with a structured out-of-policy approval chain for the exceptions that legitimately need a human signature.

The platform models the full reimbursement journey as a sequence of cooperating resources. A traveler requests a trip against an authorized budget; the system pins the active policy and screens the request for out-of-policy budget exposure. Once a trip is authorized, finance can issue a funded virtual card whose available balance is drawn down by authorization holds and final captures. The traveler assembles an expense report line by line — flights, lodging, meals, rental CDW, and mileage — each line capped against policy and substantiated by an OCR-verified receipt when its amount is material. Approval of the report is the reconciliation moment: lines settle, card holds become captures, and the trip's committed budget advances, all within a single atomic transaction.

Two financial models run in parallel and must not be conflated. Meals are reimbursed either as a GSA flat per diem or as capped actuals, depending on the report's chosen method, and a virtual card tracks provisional holds separately from finalized captures. The remainder of this document specifies the global contract every endpoint shares (Section 2) and then the business workflows where the detailed rules live (Section 3), before summarizing the endpoint surface (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting financial principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they are acting. The system recognizes exactly three roles, spelled precisely as `Traveler`, `Approver`, and `FinanceAdmin`. A request that omits either header, or that carries an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A syntactically valid request whose role lacks permission for the targeted operation is rejected with `ERR_UNAUTHORIZED`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Traveler`, `X-User-ID` is the `id` of the acting `Traveler`; ownership checks on any resource that references a traveler compare that resource's traveler linkage to `X-User-ID`. Concretely, a trip is owned by the traveler named in its `traveler_id`, and an expense report is owned by the traveler of the trip it reconciles. When `X-User-Role` is `Approver`, `X-User-ID` is the `id` of the acting `Approver`; an approver may act on a traveler's resources only when that approver is the traveler's recorded `manager_id`, and may decide an out-of-policy approval step only when that approver is the step's `approver_id`. An ownership failure on any of these checks is reported as `ERR_NOT_OWNER`. When `X-User-Role` is `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`, and `FinanceAdmin` is the configuration and settlement operator rather than an owner of traveler-scoped resources.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before the page begins and defaults to 0. A `limit` or `offset` outside its permitted range is rejected with `ERR_VALIDATION`.

Unless an endpoint states otherwise, every list is sorted by `created_at` in ascending order — oldest first. List responses surface `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object so a client can page deterministically.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` formatted as a UUID, with no type prefix. Resources also carry a `created_at` timestamp recorded at creation as an ISO 8601 UTC value with three fractional digits.

Most resources are mutable and additionally carry an `updated_at` timestamp and an integer `version`. The `version` starts at its initial value on creation and increments by one on every mutation — including server-driven mutations such as a computed-field recomputation or a cascade — and `updated_at` is refreshed to match. The one exception is the `PerDiemRate` resource, which is immutable GSA reference data: a `PerDiemRate` carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field. Travelers, approvers, travel policies, trip requests, virtual cards, expense reports, expense lines, receipts, and approval steps all carry the full identity quartet.

### 2.5. Monetary Precision and Rounding

All monetary amounts in this system are stored and exchanged as integer cents — there are no fractional-cent or floating-point money values in any request or response body. Where a calculation introduces a fractional cent, the rounding rule depends on the step and is specified explicitly in the relevant workflow. Two conventions recur. Where a formula divides by a scaling factor or applies a proration percentage, the result is rounded half up to the nearest whole cent — a value exactly on the half-cent boundary rounds away from zero. Where a formula instead applies the airfare advance-purchase discount, the intermediate is truncated toward zero (floored to a whole cent) rather than rounded. The precise rounding step, and whether rounding occurs per-component or on a final sum, is stated alongside each calculation in Section 3; the difference between rounding-per-day and rounding-the-sum is material and is pinned there.

### 2.6. Ordered Request Validation

Every request is validated in a fixed priority order, and the first failing check determines the error returned. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Authorization by role is next, yielding `ERR_UNAUTHORIZED` when the role may not call the endpoint at all. Existence is third: all path-referenced resources and any required foreign-key references in the body must resolve to existing entities, checked left-to-right, with the first unresolved reference yielding `ERR_NOT_FOUND`. Ownership is fourth, applied to ownership-gated transitions and decision endpoints, and yields `ERR_NOT_OWNER` when the acting entity-backed user does not own or manage the target. Body well-formedness is fifth: required fields present, enum values drawn from their permitted set, and integers non-negative — a violation yields `ERR_INVALID_REQUEST`. State legality is sixth, applied to every state-transition endpoint: if the target resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE`. Optimistic concurrency is seventh and is described below. Domain-specific business checks follow these, in the order their workflows describe.

This ordering is not cosmetic. Because authentication precedes existence, a request with bad headers against a non-existent resource reports `ERR_UNAUTHENTICATED`, not `ERR_NOT_FOUND`. Because existence precedes ownership, a request naming a resource that does not exist reports `ERR_NOT_FOUND` even when the caller would also have failed an ownership check. Because state legality is evaluated before the domain business rules that follow it, a transition attempted from the wrong state surfaces as `ERR_INVALID_STATE` rather than as a later fiscal or chain-completeness error.

### 2.7. Optimistic Concurrency on Card Issuance

Issuing a virtual card against a trip is the one operation guarded by optimistic concurrency control. The card-issuance request must carry `expected_trip_request_version` as a required field, holding the `version` of the target `TripRequest` that the client last observed. If `expected_trip_request_version` does not equal the trip's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The motivation is fiscal: a prior card issuance legitimately draws down the trip's `remaining_budget_cents` and advances the trip's `version`; a later issuance still carrying the pre-issuance version is operating on a stale view of available budget and must be refused so it cannot over-fund the trip. No other endpoint accepts or requires a version field; only card issuance performs this check.

### 2.8. Cascading Reconciliation and Consistency

The system settles all consequences of an operation atomically within the request that triggers them — there is no deferred or eventual reconciliation. When approving an expense report cascades into line approvals, card captures, and a trip-budget commitment, every one of those secondary mutations completes inside the same transaction, and each mutated resource has its `version` incremented and its `updated_at` refreshed. The detailed cascade hops are specified in Section 3 where the report-decision workflow is described. The same atomicity applies on rejection, where line voids release card holds in the same transaction. A reader should treat any computed field — a trip's `committed_amount_cents` and `remaining_budget_cents`, a card's `authorized_holds_cents`, `captured_total_cents`, and `available_balance_cents`, a report's `meal_reimbursable_cents` and `total_reimbursable_cents`, and a line's `reimbursable_amount_cents` and `in_policy` — as always reflecting the current state of its inputs immediately after the triggering operation returns.

### 2.9. Foreign-Key Resolution Order for Nested References

Several creation endpoints accept foreign-key references in the request body rather than in the path — an expense line names its `report_id` and optionally its `virtual_card_id`, a receipt names its `expense_line_id`, an approval step names its `report_id` and `approver_id`, and a report names its `trip_request_id`. Path parameters and body foreign keys are resolved left-to-right and body-declared-order respectively, and the first reference that does not resolve to an existing entity yields `ERR_NOT_FOUND` before any business rule is evaluated. This means a request that both references a missing parent and would also violate a downstream constraint reports the missing reference first.

## 3. Business Logic & Workflows

### 3.1. Policy and Reference Data Configuration

Before any travel can be requested, a `FinanceAdmin` establishes the policy and reference data that everything else is measured against. A travel policy is created in `DRAFT` status with a descriptive `name` and the full set of caps that govern reimbursement: `max_economy_fare_cents` (the per-flight-line ceiling on economy airfare), `business_class_min_hours` (the minimum scheduled flight duration in hours at which a business cabin becomes in-policy), `advance_purchase_days` (the minimum number of days between booking and departure for an advance-purchase economy fare to be in-policy), `cdw_daily_cap_cents` (the per-day ceiling on rental-car Collision Damage Waiver), `mileage_rate_milli_cents` (the personal-vehicle reimbursement rate expressed in milli-cents per mile, so that 67000 denotes sixty-seven cents per mile), and `receipt_required_threshold_cents` (the line amount at or above which a verified receipt is mandatory).

A policy moves from `DRAFT` to `ACTIVE` only when no other policy is already `ACTIVE`; activating a second policy while one is already active is rejected with `ERR_POLICY_ALREADY_ACTIVE`. The system therefore guarantees at most one active policy at any time, and that single active policy is the one pinned onto each new trip request. Retiring an `ACTIVE` policy moves it to the terminal `RETIRED` state, but only when no trip request that still references it is in `PENDING` or `PENDING_OOP_APPROVAL`; an attempt to retire a policy still referenced by such a trip is rejected with `ERR_POLICY_IN_USE`. Both activation and retirement are restricted to a `FinanceAdmin`.

GSA reference data lives in per-diem rate records, each keyed by a two-letter `state_code` and carrying the GSA maximum nightly lodging reimbursement `lodging_cap_cents` and the GSA full-day Meals & Incidental Expenses per diem `mie_cents`. These records are immutable once created and are loaded by a `FinanceAdmin`. Travelers and approvers are also provisioned by a `FinanceAdmin`: a traveler is created with an `email` (their unique login), a `full_name`, a `home_office_state` (the two-letter code of their home office), and a `manager_id` pointing to the approver who reviews that traveler's reports, and is created in `ACTIVE` status. An approver is created with an `email`, a `full_name`, and an `approval_limit_cents` denoting the maximum total reimbursable they may approve, and is likewise created `ACTIVE`. Neither travelers nor approvers have any deactivation lifecycle in scope; both remain `ACTIVE`.

### 3.2. Requesting and Authorizing a Trip

A `Traveler` opens the travel lifecycle by creating a trip request for themselves, supplying the `traveler_id` of the traveler taking the trip, the two-letter `destination_state`, an inclusive `start_date` and `end_date` (each an ISO 8601 calendar date), and a `budget_total_cents` ceiling. At creation the trip is placed in `PENDING`, its `policy_id` is pinned to whichever policy is currently `ACTIVE`, and its computed ledger fields `committed_amount_cents` and `remaining_budget_cents` are not yet initialized. If no policy is `ACTIVE` at the moment of creation, the request is rejected with `ERR_NO_ACTIVE_POLICY`. The trip must also not collide with the traveler's other live trips: a new trip whose date range overlaps any existing trip of the same traveler in `PENDING`, `PENDING_OOP_APPROVAL`, `AUTO_APPROVED`, or `APPROVED` is rejected with `ERR_TRIP_DATE_OVERLAP`. Overlap is evaluated on the closed interval from `start_date` through `end_date` inclusive on both ends, so two trips that merely touch at an endpoint — one ending on the very day another begins — are treated as overlapping and collide. A `Traveler` may also cancel a trip while it is still `PENDING`, moving it to the terminal `CANCELLED` state.

Submitting a `PENDING` trip request is the fork point of the trip lifecycle, and the acting `Traveler` must own the trip or the submission is rejected with `ERR_NOT_OWNER`. On submission the system computes `requires_oop`, the out-of-policy flag. A trip is flagged out-of-policy when its requested `budget_total_cents` is more than twice the GSA baseline for the destination over the trip's nights — that is, when `budget_total_cents` strictly exceeds two times the sum of the destination's `lodging_cap_cents` and `mie_cents`, multiplied by the number of trip nights, where the number of nights is the count of days between `start_date` and `end_date` (the later date minus the earlier date, with no inclusive adjustment). A budget exactly equal to twice that baseline is in-policy; only a strictly greater budget is out-of-policy.

The two fork branches diverge in their side effects. When `requires_oop` evaluates to false, the trip takes the in-policy branch: it sets `requires_oop` to false and moves from `PENDING` to `AUTO_APPROVED`, and the system immediately joins that branch forward to the terminal `APPROVED` state with no manual review. When `requires_oop` evaluates to true, the trip takes the out-of-policy branch: it sets `requires_oop` to true and moves from `PENDING` to `PENDING_OOP_APPROVAL`, where it awaits an approver's decision. In the out-of-policy branch, the traveler's manager renders a decision; the acting `Approver` must be the traveler's `manager_id` or the decision is rejected with `ERR_NOT_OWNER`. An approve decision moves the trip from `PENDING_OOP_APPROVAL` to `APPROVED`, and a deny decision moves it to the terminal `DENIED` state. Whether the trip reaches `APPROVED` through the auto-approved join or through manual approval, the same initialization occurs as the trip's budget ledger comes alive: `remaining_budget_cents` is initialized to the full `budget_total_cents` and `committed_amount_cents` is initialized to zero.

### 3.3. Funding the Trip: Virtual Card Issuance and Lifecycle

Once a trip is `APPROVED`, a `FinanceAdmin` may issue a virtual card to fund it. Card issuance is the supersede-style write described in Section 2.7: the request supplies a `load_limit_cents` (the total funds to load) and the `expected_trip_request_version` matching the trip's current `version`, and a mismatch is refused with `ERR_STALE_VERSION`. The card's `trip_request_id` is taken from the trip identified in the request path. The `load_limit_cents` may not exceed the trip's current `remaining_budget_cents` at the moment of issuance; an issuance whose `load_limit_cents` exceeds that remaining budget is rejected with `ERR_CARD_LIMIT_EXCEEDED`. A successful issuance creates the card in `ACTIVE` status, initializes its computed buckets `authorized_holds_cents` and `captured_total_cents` to zero so that `available_balance_cents` equals the full `load_limit_cents`, and advances the funding trip's `version` by one — which is exactly why a second concurrent issuance carrying the now-stale version is rejected.

A card's `available_balance_cents` is always its `load_limit_cents` minus its `authorized_holds_cents` minus its `captured_total_cents`. The `authorized_holds_cents` is the sum of the reimbursable amounts of every line charged to the card whose settlement is still provisional (`settlement_status` of `PENDING`), and `captured_total_cents` is the sum of the reimbursable amounts of every line charged to the card whose settlement has finalized (`settlement_status` of `SETTLED`). These two buckets are the heart of the provisional-versus-final distinction: when a line is first charged, its amount sits in `authorized_holds_cents` as a provisional reservation, reducing `available_balance_cents` while leaving `captured_total_cents` untouched; when the report approves and the line settles, the identical amount moves out of `authorized_holds_cents` and into `captured_total_cents`, leaving `available_balance_cents` unchanged by the move itself because the same figure simply shifts buckets.

A `FinanceAdmin` manages the card across its lifecycle. Freezing moves a card from `ACTIVE` to `FROZEN`; while frozen, any attempt to charge a new expense line to the card is refused with `ERR_CARD_NOT_ACTIVE`. Unfreezing returns it from `FROZEN` to `ACTIVE`. Closing moves a card to the terminal `CLOSED` state from either `ACTIVE` or `FROZEN`, but only when it has no outstanding provisional reservations — that is, when `authorized_holds_cents` equals zero; closing a card that still carries open holds is rejected with `ERR_CARD_HAS_OPEN_HOLDS`.

### 3.4. Building the Report and Its Lines

A `Traveler` reconciles a trip by creating an expense report against it, supplying the `trip_request_id` of the trip being reconciled, a `title`, and optionally a `per_diem_method`. The `per_diem_method` selects the meal-reimbursement variant and is one of `PER_DIEM` or `ITEMIZED`; when omitted it defaults to `PER_DIEM`. A new report is created in `DRAFT` status, and its computed totals `meal_reimbursable_cents` and `total_reimbursable_cents` are not yet finalized. The `return_reason` field, which records why an approver sent the report back, is empty on a fresh report.

While the report is in `DRAFT`, the traveler adds expense lines to it. Each line names the `report_id` it belongs to and a `line_type` drawn from `FLIGHT`, `LODGING`, `MEAL`, `RENTAL_CDW`, or `MILEAGE`, along with a `claimed_amount_cents` (the amount the traveler claims, which is zero for a mileage line because its reimbursement is computed from miles). A line that draws on card funds also names the `virtual_card_id` it is charged to; out-of-pocket lines such as mileage omit the card reference. The remaining inputs are type-specific and supplied only for the relevant `line_type`: a flight line carries a `cabin_class` of `ECONOMY` or `BUSINESS`, a `scheduled_hours` flight duration, and an `advance_days` count of days between booking and departure; a lodging line carries a `check_in_date` (the inclusive interval start) and a `check_out_date` (the exclusive interval end); a rental-CDW line carries a `rental_days` count; and a mileage line carries a `miles` count. Every line is created in `PENDING_REVIEW` status, and the system immediately computes its `reimbursable_amount_cents` and its `in_policy` flag according to the per-type rules in Section 3.5.

When a line names a virtual card, charging it creates a provisional hold on that card: the line's `settlement_status` becomes `PENDING` and its reimbursable amount is reflected in the card's `authorized_holds_cents`. A line may only be charged to a card that is `ACTIVE`, otherwise the charge is refused with `ERR_CARD_NOT_ACTIVE`, and the line's `reimbursable_amount_cents` may not exceed the card's current `available_balance_cents`, otherwise it is refused with `ERR_CARD_LIMIT_EXCEEDED`. A line with no card reference — the out-of-pocket case, typically mileage — carries `settlement_status` of `NONE` and never touches a card ledger. Lodging lines additionally may not overlap one another within the same report: their stays are compared on the half-open interval from `check_in_date` up to but not including `check_out_date`, so two stays where one's `check_out_date` equals the next one's `check_in_date` are adjacent and permitted, while any genuine overlap is rejected with `ERR_LODGING_OVERLAP`. A traveler may remove a line from a `DRAFT` report; deleting a line that holds a provisional reservation releases that hold back to its card.

### 3.5. Per-Line Reimbursement Caps

Each line's `reimbursable_amount_cents` is the policy-capped amount the system will actually reimburse, and its `in_policy` flag records whether the traveler's claim fell within policy. The rules differ by `line_type`, and all amounts are integer cents.

For a flight line, the cap depends on cabin. When `cabin_class` is `BUSINESS`, the line is in-policy only if `scheduled_hours` is at least `business_class_min_hours`; a business cabin booked on a flight whose scheduled duration is below that minimum is out-of-policy, so `in_policy` is set to false. A business fare that clears the duration minimum is not capped — its cap equals the claimed amount itself. When `cabin_class` is `ECONOMY`, the cap starts at `max_economy_fare_cents`, but if the booking was late — `advance_days` less than `advance_purchase_days` — the cap is reduced to eighty percent of `max_economy_fare_cents`, with that eighty-percent figure truncated toward zero to a whole cent. In every flight case the `reimbursable_amount_cents` is the smaller of `claimed_amount_cents` and the cap, and if `claimed_amount_cents` exceeds the cap the line is marked out-of-policy.

For a rental-CDW line, the cap is `cdw_daily_cap_cents` multiplied by `rental_days`; the `reimbursable_amount_cents` is the smaller of `claimed_amount_cents` and that cap, and the line is in-policy when `claimed_amount_cents` is less than or equal to the cap. For a lodging line, the system first computes the number of nights as the day count of the half-open interval from `check_in_date` to `check_out_date` (check-out minus check-in), then sets the cap to the destination's GSA `lodging_cap_cents` — looked up by the trip's `destination_state` — multiplied by that night count; the `reimbursable_amount_cents` is the smaller of `claimed_amount_cents` and the cap, and the line is in-policy when `claimed_amount_cents` is less than or equal to the cap. For a mileage line, the `reimbursable_amount_cents` is the product of `miles` and the policy's `mileage_rate_milli_cents`, divided by one thousand to convert milli-cents into cents, with that single division rounded half up to a whole cent; a mileage line is always in-policy. Meal lines do not produce a per-line reimbursable amount of their own: a meal line's `reimbursable_amount_cents` is zero, and meal reimbursement is computed at the report level as described in Section 3.6 so that meal spend is never double-counted.

### 3.6. Meal Reimbursement and Report Totals

Meal reimbursement is a dual-variant calculation evaluated when the report is submitted and again when it is approved, and it populates the report's `meal_reimbursable_cents`. Both variants build on the GSA M&IE per diem for the trip's destination — the `mie_cents` looked up by the trip's `destination_state` — applied across the trip's days. The number of trip days is the count of days between the trip's `start_date` and `end_date` plus one, because both endpoints are inclusive. The per-diem total prorates the first and last day at seventy-five percent of the daily M&IE rate while paying full rate for each interior day, and the order of rounding is fixed: each day's amount is rounded half up to whole cents first, and only then are the days summed — the system does not sum first and round once. Concretely, when a trip spans a single day, the per-diem total is the daily rate multiplied by seventy-five percent and then rounded half up. When a trip spans more than one day, the per-diem total is the rounded-half-up seventy-five-percent first-day amount, plus the rounded-half-up seventy-five-percent last-day amount, plus the full daily rate for each of the interior days (the number of interior days being the trip day count minus two).

The two methods then diverge from that per-diem total. Under the `PER_DIEM` method, the report ignores the claimed amounts on its meal lines entirely and sets `meal_reimbursable_cents` to the GSA per-diem total computed above. Under the `ITEMIZED` method, the report sums the `claimed_amount_cents` of all its meal lines and sets `meal_reimbursable_cents` to the smaller of that actual-spend sum and the same per-diem total — actuals are reimbursed but capped at the per-diem ceiling. The two methods take identical inputs and produce identical results only when actual meal spend equals the flat per diem; whenever they differ, the chosen `per_diem_method` is what decides the figure.

The report's `total_reimbursable_cents` is then assembled in a pinned order. The meal portion is computed first, because `meal_reimbursable_cents` does not depend on any per-line meal reimbursable. The total is then `meal_reimbursable_cents` plus the sum of the `reimbursable_amount_cents` of every line that is neither rejected nor a meal line — that is, every line whose `status` is not `REJECTED` and whose `line_type` is not `MEAL`. Meal lines are excluded from this sum because their own per-line reimbursable is zero and their value is already captured in `meal_reimbursable_cents`, so including them would double-count. Both `meal_reimbursable_cents` and `total_reimbursable_cents` are recomputed at submission and recomputed again at approval.

### 3.7. Substantiating Lines: Receipts and OCR

A `Traveler` substantiates a line by uploading a receipt for it, supplying the `expense_line_id` the receipt belongs to (one receipt per line) and an `image_ref` storage reference for the uploaded image. The receipt is created in `UPLOADED` status with its OCR fields unpopulated. A `FinanceAdmin` then drives the receipt through its verification lifecycle. Running OCR moves the receipt from `UPLOADED` to `OCR_PROCESSED` and populates `ocr_amount_cents` and `ocr_merchant` from the supplied OCR payload. From `OCR_PROCESSED`, a receipt can be verified or disputed: verifying moves it to `VERIFIED`, but only when its `ocr_amount_cents` equals the `claimed_amount_cents` of the linked expense line — a mismatch is rejected with `ERR_RECEIPT_AMOUNT_MISMATCH`. Marking a receipt disputed moves it from `OCR_PROCESSED` to `DISPUTED`, and a disputed receipt can later be re-verified, again moving to `VERIFIED` only when `ocr_amount_cents` equals the linked line's `claimed_amount_cents`, with the same `ERR_RECEIPT_AMOUNT_MISMATCH` guarding the re-verification.

Receipts matter at submission time. Any line whose computed `reimbursable_amount_cents` is at or above the policy's `receipt_required_threshold_cents` must have a `VERIFIED` receipt before its report may be submitted; a report submission with such a line lacking a verified receipt is rejected with `ERR_RECEIPT_REQUIRED`. Lines below the threshold carry no receipt requirement.

### 3.8. Submitting and Deciding the Report

Submitting a report is restricted to the owning `Traveler` — the traveler of the report's trip — and is rejected with `ERR_NOT_OWNER` otherwise. Submission carries several preconditions evaluated in addition to the standard ordered checks. The report's trip must already be `APPROVED`, or the submission is rejected with `ERR_TRIP_NOT_APPROVED`. The report must contain at least one expense line, or it is rejected with `ERR_REPORT_EMPTY`. And the receipt requirement of Section 3.7 must be satisfied for every material line, or it is rejected with `ERR_RECEIPT_REQUIRED`. A valid submission moves the report from `DRAFT` to `SUBMITTED` and recomputes `meal_reimbursable_cents` and `total_reimbursable_cents`.

A `SUBMITTED` report awaits a decision from the traveler's manager; the acting `Approver` must be the report traveler's `manager_id` or the decision is rejected with `ERR_NOT_OWNER`. The decision endpoint accepts a `decision` and, for the return path, a `return_reason`. There are three decision branches out of `SUBMITTED`, each carrying its own preconditions and effects.

A return decision sends the report from `SUBMITTED` back to `RETURNED` for revision; it requires a `return_reason` in the payload, and a return decision without one is rejected with `ERR_RETURN_REASON_REQUIRED`. The supplied reason is stored on the report's `return_reason`. A `RETURNED` report can be reopened by its owning `Traveler`, moving it from `RETURNED` back to `DRAFT`, clearing `return_reason`, and making its lines editable again — this is the revision cycle `DRAFT → SUBMITTED → RETURNED → DRAFT`.

A reject decision moves the report from `SUBMITTED` to the terminal `REJECTED` state and triggers the rejection cascade. In that cascade, every expense line still in `PENDING_REVIEW` transitions to `REJECTED`, and each rejected line that held a provisional hold (`settlement_status` of `PENDING`) transitions to `VOID`, releasing its hold on its virtual card; each affected card then recomputes its `authorized_holds_cents` and `available_balance_cents` so the released funds return to availability.

An approve decision moves the report from `SUBMITTED` to the terminal `APPROVED` state, but only after two further gates. First, if the report has any out-of-policy line, every approval step in its out-of-policy chain must already have a decision of `APPROVED`; an approve attempt while the chain is incomplete is rejected with `ERR_OOP_CHAIN_INCOMPLETE`. Second, the trip's `remaining_budget_cents` must be at least the report's `total_reimbursable_cents`; an approve that would overcommit the trip is rejected with `ERR_BUDGET_EXCEEDED`. When both gates pass, the approval cascade runs as a single atomic sequence: every expense line still in `PENDING_REVIEW` transitions to `APPROVED`; each approved line whose `settlement_status` is `PENDING` then transitions to `SETTLED`, moving its held amount from the card's authorized holds into its captures; each affected virtual card recomputes its `authorized_holds_cents`, `captured_total_cents`, and `available_balance_cents`; and finally the trip's `committed_amount_cents` is increased by the report's `total_reimbursable_cents` and its `remaining_budget_cents` is recomputed. A trip's `committed_amount_cents` is always the sum of `total_reimbursable_cents` across every `APPROVED` report charged to that trip, and `remaining_budget_cents` is `budget_total_cents` minus `committed_amount_cents`.

### 3.9. The Out-of-Policy Approval Chain

When a report carries lines that fall outside policy, those exceptions are adjudicated through an ordered approval chain that a `FinanceAdmin` constructs. Each approval step is created against a `report_id`, names the `approver_id` assigned to adjudicate it, and carries a `step_order` — a one-based position in the chain. Steps are created with a `decision` of `PENDING`, and the `comment` field is empty until a decision is recorded.

The chain adjudicates strictly in ascending `step_order`. The assigned `Approver` decides a step by supplying a `decision` of either approve or reject, and optionally a `comment` recorded with the decision; the acting approver must be the step's `approver_id` or the decision is rejected with `ERR_NOT_OWNER`. Before a step may be decided at all, every step for the same report with a smaller `step_order` must already have a `decision` of `APPROVED`; deciding a step while an earlier one is still outstanding is rejected with `ERR_OOP_STEP_OUT_OF_ORDER`. This ordering precondition applies equally to an approve decision (which moves the step to `APPROVED`) and a reject decision (which moves the step to `REJECTED`) — both branches require the lower-ordered steps to be settled first. The completed chain is what the report-approval gate in Section 3.8 consults: only when every step is `APPROVED` may a report with out-of-policy lines itself be approved.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. State transitions and other modifications to an existing resource return `200 OK`, and a successful line deletion returns `204 No Content`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/travelers` | Create a Traveler | FinanceAdmin |
| GET | `/travelers/{travelerId}` | Get a Traveler | FinanceAdmin, Traveler, Approver |
| GET | `/travelers` | List Travelers (filter by `manager_id`) | FinanceAdmin, Approver |
| POST | `/approvers` | Create an Approver | FinanceAdmin |
| GET | `/approvers/{approverId}` | Get an Approver | FinanceAdmin, Approver |
| POST | `/travel-policies` | Create a TravelPolicy (DRAFT) | FinanceAdmin |
| GET | `/travel-policies/{policyId}` | Get a TravelPolicy | FinanceAdmin, Traveler, Approver |
| POST | `/travel-policies/{policyId}/activate` | Activate a DRAFT policy | FinanceAdmin |
| POST | `/travel-policies/{policyId}/retire` | Retire an ACTIVE policy | FinanceAdmin |
| POST | `/per-diem-rates` | Create a PerDiemRate | FinanceAdmin |
| GET | `/per-diem-rates/{rateId}` | Get a PerDiemRate | FinanceAdmin, Traveler, Approver |
| GET | `/per-diem-rates` | List PerDiemRates (filter by `state_code`) | FinanceAdmin, Traveler, Approver |
| POST | `/trip-requests` | Create a TripRequest (pins the ACTIVE policy) | Traveler |
| GET | `/trip-requests/{tripId}` | Get a TripRequest | FinanceAdmin, Traveler, Approver |
| GET | `/trip-requests` | List TripRequests (filter by `traveler_id` or `policy_id`) | FinanceAdmin, Traveler, Approver |
| POST | `/trip-requests/{tripId}/submit` | Submit a TripRequest for authorization | Traveler |
| POST | `/trip-requests/{tripId}/decision` | Decide an out-of-policy TripRequest | Approver |
| POST | `/trip-requests/{tripId}/cancel` | Cancel a PENDING TripRequest | Traveler |
| POST | `/trip-requests/{tripId}/virtual-cards` | Issue a VirtualCard against an APPROVED trip | FinanceAdmin |
| GET | `/virtual-cards/{cardId}` | Get a VirtualCard | FinanceAdmin, Traveler |
| GET | `/virtual-cards` | List VirtualCards (filter by `trip_request_id`) | FinanceAdmin, Traveler |
| POST | `/virtual-cards/{cardId}/freeze` | Freeze a card | FinanceAdmin |
| POST | `/virtual-cards/{cardId}/unfreeze` | Unfreeze a card | FinanceAdmin |
| POST | `/virtual-cards/{cardId}/close` | Close a card (no open holds) | FinanceAdmin |
| POST | `/expense-reports` | Create an ExpenseReport (DRAFT) | Traveler |
| GET | `/expense-reports/{reportId}` | Get an ExpenseReport | FinanceAdmin, Traveler, Approver |
| GET | `/expense-reports` | List ExpenseReports (filter by `trip_request_id`) | FinanceAdmin, Traveler, Approver |
| POST | `/expense-reports/{reportId}/submit` | Submit a DRAFT report for review | Traveler |
| POST | `/expense-reports/{reportId}/decision` | Decide a SUBMITTED report (approve/reject/return) | Approver |
| POST | `/expense-reports/{reportId}/reopen` | Reopen a RETURNED report to DRAFT | Traveler |
| POST | `/expense-lines` | Add an ExpenseLine to a DRAFT report | Traveler |
| GET | `/expense-lines/{lineId}` | Get an ExpenseLine | FinanceAdmin, Traveler, Approver |
| GET | `/expense-lines` | List ExpenseLines (filter by `report_id` or `virtual_card_id`) | FinanceAdmin, Traveler, Approver |
| DELETE | `/expense-lines/{lineId}` | Remove a line from a DRAFT report | Traveler |
| POST | `/receipts` | Upload a Receipt for an ExpenseLine | Traveler |
| GET | `/receipts/{receiptId}` | Get a Receipt | FinanceAdmin, Traveler, Approver |
| GET | `/receipts` | List Receipts (filter by `expense_line_id`) | FinanceAdmin, Traveler, Approver |
| POST | `/receipts/{receiptId}/ocr` | Run OCR on a receipt | FinanceAdmin |
| POST | `/receipts/{receiptId}/verify` | Verify an OCR'd or disputed receipt | FinanceAdmin |
| POST | `/receipts/{receiptId}/dispute` | Mark an OCR'd receipt disputed | FinanceAdmin |
| POST | `/approval-steps` | Add an out-of-policy approval step to a report | FinanceAdmin |
| GET | `/approval-steps/{stepId}` | Get an ApprovalStep | FinanceAdmin, Traveler, Approver |
| GET | `/approval-steps` | List ApprovalSteps (filter by `report_id` or `approver_id`) | FinanceAdmin, Traveler, Approver |
| POST | `/approval-steps/{stepId}/decision` | Decide an out-of-policy step (ascending step_order) | Approver |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POLICY_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_POLICY_IN_USE` | 409 Conflict |
| `ERR_NO_ACTIVE_POLICY` | 409 Conflict |
| `ERR_TRIP_DATE_OVERLAP` | 409 Conflict |
| `ERR_TRIP_NOT_APPROVED` | 409 Conflict |
| `ERR_REPORT_EMPTY` | 409 Conflict |
| `ERR_RECEIPT_REQUIRED` | 409 Conflict |
| `ERR_RECEIPT_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_LODGING_OVERLAP` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARD_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_CARD_HAS_OPEN_HOLDS` | 409 Conflict |
| `ERR_OOP_CHAIN_INCOMPLETE` | 409 Conflict |
| `ERR_OOP_STEP_OUT_OF_ORDER` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_RETURN_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
