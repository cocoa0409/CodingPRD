# Sauce & Condiment Co-Packing API — Product Requirements Document

## 1. Introduction

Contract manufacturing of sauces and condiments is a business of constrained promises: a brand owner hands over a recipe, and the co-packer must prove the formula scales beyond a test batch, document the thermal process to a food-safety authority, book shared kettles without cross-contaminating allergens, source or consign every ingredient, guarantee that bottles, caps, labels, and cases are physically on the floor, and only then bill for what was actually produced. This document specifies the Sauce & Condiment Co-Packing API, the system of record for that entire lifecycle, exposing every collection under the `/copack` mount.

The API follows one formula from intake to release: drafting and scale-up trials in the pilot plant, process-authority letters for acidified and low-acid products, formula approval, production runs on kettle lines with allergen-conditional changeover buffers and minimum-run billing, quality holds governed by statutory destroy gates and segregated disposition duties, and private-label compliance gating final release. Access is deliberately narrow — operations administrators run the plant, brand owners see only their own products, an external process authority issues letters, and quality reviewers hold the disposition pen — so that no single actor can both raise a quality concern and sign off on its resolution.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly four roles: `OpsAdmin`, `Customer`, `ProcessAuthority`, and `QAReviewer`. A request missing either header, or carrying a role string other than these four, is rejected with an `ERR_MISSING_OR_INVALID_USER_CONTEXT` error. Access to every endpoint is further restricted by role; an attempt to perform an action outside the caller's designated role set is rejected with an `ERR_FORBIDDEN` error.

The meaning of `X-User-ID` depends on the role presented:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a `CustomerAccount` compare the resource's customer-chain foreign key to `X-User-ID`. A caller in this role who creates a formula must pass a `customer_id` equal to their own `X-User-ID`, and every later access — the formula itself, its ingredient supplies, trials, letters, and labels, its production runs, and the quality holds placed on those runs — is scoped to that same ownership chain. Acting on a resource outside the chain is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `OpsAdmin`, `ProcessAuthority`, or `QAReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a `QualityHold` where a hold-creation transition writes it) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — `CustomerAccount`, `Formula`, `IngredientSupply`, `PilotCell`, `ScaleUpTrial`, `ProcessAuthorityLetter`, `KettleLine`, `PackagingComponent`, `ProductionRun`, `QualityHold`, and `LabelApproval` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource.
- `version` (integer): a system-managed counter that increments with every modification to the resource.

A modification is any change whatsoever — field edits, state transitions, and derived-field reconciliation all count. Consequently, when one operation cascades into several resources (for example, a reformulation that supersedes a letter and cancels runs, or a confirmation that adjusts stock and billing), each resource actually mutated by the cascade has its own `updated_at` refreshed and its own `version` incremented. All mutations are immediately consistent: the response of the request that caused them reflects the new state, and subsequent reads observe it.

### 2.5. Optimistic Concurrency Control

Two write operations carry mandatory optimistic concurrency control; no other endpoint accepts a version field.

- Updating a formula's specification requires the non-optional input field `expected_formula_version`, carrying the client's last observed `version` of that `Formula`. If the formula's current `version` no longer matches the supplied value — because another write has advanced it since the client last read the resource — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than overwriting changes the client never saw.
- Adjusting a packaging component's stock requires the non-optional input field `expected_component_version`, carrying the client's last observed `version` of that `PackagingComponent`. The same mismatch handling applies: rejection with `ERR_STALE_VERSION` (HTTP 412) instead of clobbering stock changes the client never saw.

### 2.6. Money, Measurements, and Rounding

All monetary values in the system are integer cents — credit limits, billed exposure, rates, fees, and every charge field end in `_cents` and carry whole-cent precision. Charge arithmetic observes a strict rounding discipline: each extended line (an ingredient line or a packaging line) is rounded half-up to whole cents before any summation takes place, and the totals are sums of those rounded lines. The system never sums unrounded line values and rounds once at the end.

Two computed hold metrics, `letter_deviation` and `statutory_margin`, are decimal quantities rather than money; they are rounded half-up to two decimal places. Measured process values (`measured_ph`, `measured_water_activity`) and ingredient flow rates (`quantity_per_unit`) are decimal inputs preserved as submitted.

### 2.7. Validation Order and Error Precedence

Every request travels through the same ordered validation pipeline, and a failure at any stage masks every later stage — the caller always receives the earliest applicable error. The stages, in order, are:

1. **User context.** `X-User-ID` and `X-User-Role` must both be present, and the role must be one of the four declared role names; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).
2. **Role authorization.** The presented role must appear in the endpoint's authorized role set; otherwise `ERR_FORBIDDEN` (HTTP 403).
3. **Customer ownership.** When the role is `Customer`, `X-User-ID` must equal the owning `customer_id` of the resource chain — the formula's own `customer_id`, the run's formula's, the hold's run's formula's, and likewise for supplies, trials, letters, and labels via their formula; otherwise `ERR_FORBIDDEN` (HTTP 403).
4. **Existence.** Path identifiers are validated left to right, each mapping to its resource-specific 404 — `ERR_CUSTOMER_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`, `ERR_INGREDIENT_SUPPLY_NOT_FOUND`, `ERR_PILOT_CELL_NOT_FOUND`, `ERR_TRIAL_NOT_FOUND`, `ERR_LETTER_NOT_FOUND`, `ERR_KETTLE_LINE_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_LABEL_NOT_FOUND`. Only after the path resolves are foreign keys in the request body — `formula_id`, `kettle_line_id`, `pilot_cell_id`, `production_run_id`, and each `component_id` inside `packaging_requirements` — checked against the same 404 family.
5. **Request shape.** Required fields must be present, types must be valid, enum values must be members of their declared sets, quantities must be strictly positive where required, `scheduled_end` must be strictly after `scheduled_start`, `unit_cost_cents` must be present when a supply's `sourcing_mode` is `COPACKER_SUPPLIED`, `measured_ph` must be present when a hold's `reason_category` is `PH_DEVIATION`, `measured_water_activity` must be present when it is `AW_DEVIATION`, and consignment receipts are accepted only for `CUSTOMER_SUPPLIED` lines. Any violation is `ERR_INVALID_REQUEST` (HTTP 400).
6. **State preconditions.** The target entity must be in the status the operation requires — formula gates (`ERR_FORMULA_NOT_DRAFT`, `ERR_FORMULA_NOT_TRIAL_PASSED`, `ERR_FORMULA_NOT_APPROVED`), trial gates (`ERR_TRIAL_NOT_SCHEDULED`), letter gates (`ERR_LETTER_NOT_SUBMITTED`), run gates (`ERR_RUN_NOT_PLANNED`, `ERR_RUN_NOT_COMPLETABLE`, `ERR_RUN_NOT_COMPLETED`, `ERR_RUN_NOT_CANCELLABLE`), hold gates (`ERR_HOLD_NOT_OPEN`), and label gates (`ERR_LABEL_NOT_DRAFT`, `ERR_LABEL_NOT_SUBMITTED`). All are HTTP 409.
7. **Statutory safety.** The destroy gate on hold disposition (`ERR_STATUTORY_DESTROY_REQUIRED`, HTTP 409) and the scheduled-process bounds on letter submission (`ERR_INVALID_PROCESS_LIMITS`, HTTP 422) are evaluated after state gates and before the remaining business constraints.
8. **Domain constraints.** Scheduling conflicts (`ERR_KETTLE_LINE_CONFLICT`, `ERR_PILOT_CELL_CONFLICT`), material shortages (`ERR_PACKAGING_SHORTAGE`, `ERR_INGREDIENT_SHORTAGE`), capacity limits (`ERR_BATCH_EXCEEDS_CAPACITY`), label allergen declaration match (`ERR_LABEL_ALLERGEN_MISMATCH`, HTTP 422), disposition-owner routing (`ERR_DISPOSITION_OWNER_MISMATCH`, HTTP 403), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), and the stock floor on inventory adjustment (`ERR_STOCK_BELOW_RESERVED`).
9. **Letter-revision freshness.** Activation verifies that the letter's pinned revision still matches the formula's current revision; otherwise `ERR_LETTER_REVISION_STALE` (HTTP 409).
10. **Credit.** The credit check is always the final gate of run confirmation, so a financing breach never masks, and is never masked by, an operational conflict: `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Formula Intake

Before any product work begins, an `OpsAdmin` registers the brand owner as a **CustomerAccount**, supplying the `brand_name`, a primary `contact_email`, and a `credit_limit_cents` ceiling of zero or more that bounds how much unpaid billing the customer may carry. The account's `default_disposition_owner` — either `CUSTOMER` or `COPACKER` — decides who will be allowed to disposition quality holds raised against that customer's runs; when omitted at creation it defaults to `COPACKER`. Every account begins with an `outstanding_billed_cents` of zero. That figure is the account's live billing exposure: it rises by a run's estimate at confirmation, moves by the difference between the final charge and whatever was previously applied at each completion, falls by the estimate when a confirmed run is cancelled, and falls by the final charge when a produced batch is destroyed.

Formula intake is shared between `OpsAdmin` and the owning `Customer`. A new **Formula** records the owning `customer_id`, a `product_name`, the customer's `sku_code`, a `process_category` of `ACIDIFIED`, `LOW_ACID`, or `ACID`, an `allergen_class` of `NONE`, `GLUTEN`, `SOY`, `NUT`, or `DAIRY`, the contractual `min_run_units` of at least one, and a `unit_rate_cents` co-pack fee of zero or more per billed unit. The process category drives the entire regulatory path: `ACIDIFIED` and `LOW_ACID` formulas may not reach approval without an active process-authority letter, whereas `ACID` formulas are letter-exempt. A formula is born in `DRAFT` status with `revision` 1. The formula catalogue supports filtering by `customer_id` and `status`; a `Customer` caller only ever sees their own formulas.

While a formula remains in `DRAFT`, its specification may be revised by an `OpsAdmin` or the owning `Customer` — any subset of `product_name`, `process_category`, `allergen_class`, `min_run_units`, and `unit_rate_cents` may be replaced. Attempting such an update against a formula that has left `DRAFT` is rejected with `ERR_FORMULA_NOT_DRAFT`, and the write carries the optimistic-concurrency discipline of §2.5 via `expected_formula_version`; a successful update increments the formula's `version`.

Each ingredient line of the recipe becomes an **IngredientSupply**, again creatable only while the formula is in `DRAFT` (otherwise `ERR_FORMULA_NOT_DRAFT`). A supply line carries the `formula_id` it belongs to, an `ingredient_name`, a `sourcing_mode`, a strictly positive `quantity_per_unit` describing how many ingredient units one finished unit consumes, and a `unit_cost_cents`. The sourcing mode splits two worlds: `CUSTOMER_SUPPLIED` means the brand consigns the ingredient and the co-packer merely availability-checks it, while `COPACKER_SUPPLIED` means the co-packer procures the ingredient and its cost flows into run charges — which is why `unit_cost_cents` is mandatory for `COPACKER_SUPPLIED` lines (its absence is an `ERR_INVALID_REQUEST`) and disregarded for consigned ones. A supply's `consigned_units_on_hand` starts at zero. Supply listings may be filtered by `formula_id`.

Consignment stock arrives through receipts recorded by an `OpsAdmin` or the owning `Customer`, each carrying a strictly positive `quantity` that is added to the line's `consigned_units_on_hand`, incrementing the supply's `version`. Receipts are rejected with `ERR_INVALID_REQUEST` when the target line is not `CUSTOMER_SUPPLIED` — co-packer-procured ingredients have no consignment balance.

### 3.2. Scale-Up Trials and the Pilot Plant

Scale-up work happens in pilot plant cells. An `OpsAdmin` registers each **PilotCell** with a `cell_name` and a `max_batch_units` of at least one, bounding the largest trial batch the cell can run.

Scheduling a **ScaleUpTrial** is an `OpsAdmin`-only action that takes the `formula_id`, the `pilot_cell_id`, a `batch_size_units` of at least one, and a window from `scheduled_start` to `scheduled_end`, with the end strictly after the start (an inverted window is an `ERR_INVALID_REQUEST`). The formula must currently be in `DRAFT` — scheduling against a formula in any other status is rejected with `ERR_FORMULA_NOT_DRAFT` — and a successful scheduling moves the formula from `DRAFT` to `IN_TRIAL`. A batch larger than the cell's `max_batch_units` is refused with `ERR_BATCH_EXCEEDS_CAPACITY`. Pilot cells enforce a zero-buffer touch-allowed booking rule: only `SCHEDULED` trials occupy a cell, and a new window that merely touches an occupying window — one's `scheduled_end` exactly equal to the other's `scheduled_start` — is permitted, while any genuine overlap is rejected with `ERR_PILOT_CELL_CONFLICT`. Trial listings may be filtered by `formula_id` and `pilot_cell_id`.

When the trial cook finishes, an `OpsAdmin` records the outcome with a `passed` flag and the `yield_units` of good product obtained (zero or more). The trial must still be `SCHEDULED`; recording results against a trial in any other status is rejected with `ERR_TRIAL_NOT_SCHEDULED`. A passing trial moves to `PASSED`, its `yield_units` is recorded, and the formula advances out of `IN_TRIAL` — to `TRIAL_PASSED` for `ACIDIFIED` and `LOW_ACID` products, or directly to `APPROVED` for `ACID` products, which are letter-exempt and need no further regulatory step. A failing trial moves to `FAILED` and sends the formula back from `IN_TRIAL` to `DRAFT`, opening the revision loop: adjust the recipe in `DRAFT`, then trial again. Cancelling a trial follows the same discipline — only a `SCHEDULED` trial may be cancelled (`ERR_TRIAL_NOT_SCHEDULED`), the trial becomes `CANCELLED`, and its formula likewise returns from `IN_TRIAL` to `DRAFT`. `PASSED`, `FAILED`, and `CANCELLED` are terminal states for a trial.

### 3.3. Process Authority Letters, Formula Approval, and Reformulation

For `ACIDIFIED` and `LOW_ACID` products, approval flows through a **ProcessAuthorityLetter** issued by an external `ProcessAuthority`. Submitting a letter records the `formula_id`, the `formula_revision` it covers (at least one), the `authority_name`, a `letter_number` reference, and the scheduled-process limits `max_ph` and `max_water_activity`. Submission requires the formula to be in `TRIAL_PASSED` or `APPROVED` — any other formula status is rejected with `ERR_FORMULA_NOT_TRIAL_PASSED` — and the process limits themselves must sit inside statutory bounds: `max_ph` strictly greater than zero and strictly below 4.6, `max_water_activity` strictly greater than zero and strictly below 1.0. A letter whose limits fall outside those bounds is rejected with `ERR_INVALID_PROCESS_LIMITS`. Within the statutory bounds, the letter's thresholds are the contract's deviation lines: a batch's pH deviates when its measured value exceeds `max_ph`, while water activity deviates when its measured value reaches or exceeds `max_water_activity`. A submitted letter begins life in `SUBMITTED` status. Letter listings may be filtered by `formula_id`.

Activation, also `ProcessAuthority`-only, turns a `SUBMITTED` letter into the formula's governing document. Three gates apply, in pipeline order: the letter must be `SUBMITTED` (`ERR_LETTER_NOT_SUBMITTED`); the formula must be in `TRIAL_PASSED` or `APPROVED` (`ERR_FORMULA_NOT_TRIAL_PASSED`); and, checked after the state gates, the letter's `formula_revision` must equal the formula's current `revision` — a letter drafted against an older revision is stale and rejected with `ERR_LETTER_REVISION_STALE`. Activation carries two side effects: every other `ACTIVE` letter for the same formula is moved to `SUPERSEDED`, so at most one letter per formula is ever `ACTIVE`, and a formula sitting in `TRIAL_PASSED` advances to `APPROVED` (a formula already `APPROVED` simply stays there). Letters can also leave `ACTIVE` without any client action: whenever another letter for the same formula activates, or the formula is reformulated, the system moves the displaced letter to `SUPERSEDED`.

Reformulation is the intentional reset of an approved product. An `OpsAdmin` or the owning `Customer` may reformulate a formula that is currently `APPROVED` — against any other status the request is rejected with `ERR_FORMULA_NOT_APPROVED`. The formula returns to `DRAFT`, its `revision` increments by one, and its `version` advances. The cascade is deliberately destructive: the formula's `ACTIVE` letter, if any, becomes `SUPERSEDED`; every production run of the formula in `PLANNED` or `CONFIRMED` is cancelled; and for each such run that was `CONFIRMED`, its packaging reservations are released (each component's `reserved_units` reduced by that run's requirement), its consigned ingredients are restored (each `CUSTOMER_SUPPLIED` line's `consigned_units_on_hand` increased by `quantity_per_unit` multiplied by the run's `planned_units`), and its estimate is refunded (the customer's `outstanding_billed_cents` reduced by the run's `estimated_charge_cents`). The formula then re-enters the pipeline from `DRAFT`: new trial, new letter pinned to the new revision, fresh approval.

### 3.4. Production Resources and Run Planning

Production runs execute on kettle/fill lines. An `OpsAdmin` registers each **KettleLine** with a `line_name` and a `capacity_units` of at least one, the maximum finished units a single run on that line may produce.

Packaging is tracked as **PackagingComponent** stock. An `OpsAdmin` creates a component with a `component_name`, a `component_type` of `BOTTLE`, `CAP`, `LABEL`, or `CASE`, a `unit_cost_cents` of zero or more, and an `initial_on_hand_units` of zero or more that seeds physical stock. At creation `on_hand_units` equals `initial_on_hand_units` and `reserved_units` is zero; the derived `available_units` is always `on_hand_units` minus `reserved_units`. One invariant holds at all times: `on_hand_units` never drops below `reserved_units`. When an `OpsAdmin` adjusts stock by setting a new `on_hand_units`, a value below the current `reserved_units` is rejected with `ERR_STOCK_BELOW_RESERVED`, and the write is guarded by `expected_component_version` per §2.5, incrementing the component's `version` on success.

A **ProductionRun** is created by an `OpsAdmin` with a `formula_id`, a `kettle_line_id`, `planned_units` of at least one, a cook-and-fill window from `scheduled_start` to `scheduled_end` (end strictly after start, else `ERR_INVALID_REQUEST`), and a `packaging_requirements` array whose lines each pair a `component_id` with a `quantity_per_unit`; the array may legitimately be empty. The formula must be in `TRIAL_PASSED` or `APPROVED` — attempting to plan a run against a formula still in `DRAFT` or `IN_TRIAL` is rejected with `ERR_FORMULA_NOT_APPROVED` — and `planned_units` beyond the line's `capacity_units` is refused with `ERR_BATCH_EXCEEDS_CAPACITY`. Creation pins the formula's current `revision` into the run's `formula_revision`, so the run forever records which recipe revision it was planned against, and the run begins in `PLANNED` status. Until confirmation, `changeover_fee_cents` and `estimated_charge_cents` carry no value; until completion, `actual_units_produced`, `measured_ph`, `measured_water_activity`, and `final_charge_cents` remain unset. Run listings may be filtered by `formula_id`, `kettle_line_id`, and `status`.

### 3.5. Run Confirmation: Changeover Fees, Reservations, and Estimated Billing

Confirmation is the commitment point of a run, performed by an `OpsAdmin`, and its preconditions evaluate in the pipeline order of §2.7 — state gates first, scheduling and material constraints next, credit last. The run must be in `PLANNED` (`ERR_RUN_NOT_PLANNED`) and its formula must be `APPROVED` (`ERR_FORMULA_NOT_APPROVED`).

The kettle-line interval rule guards against cross-contamination on shared equipment. A kettle line is considered occupied by its runs in `CONFIRMED`, `COMPLETED`, `ON_HOLD`, `REWORK`, and `RELEASED`; runs in `PLANNED`, `CANCELLED`, or `DESTROYED` do not occupy the line. Between the confirming run and each occupier, a required gap applies: four hours when the two runs' formulas have different `allergen_class` values, otherwise one hour. When the occupier's window ends at or before the confirming run's `scheduled_start`, a conflict exists exactly when the gap between the occupier's `scheduled_end` and the confirming run's `scheduled_start` is smaller than the required gap — a gap of exactly the required size is acceptable. When instead the confirming run's window ends at or before the occupier's `scheduled_start`, the symmetric test applies to the gap between the confirming run's `scheduled_end` and the occupier's `scheduled_start`. In every other arrangement the windows intersect outright. Any conflict rejects the confirmation with `ERR_KETTLE_LINE_CONFLICT`.

The same occupancy picture determines the changeover fee, computed once at confirmation and locked into `changeover_fee_cents`. The predecessor is the most recent prior occupant of the same line: among occupiers whose `scheduled_end` falls at or before the confirming run's `scheduled_start`, the one with the latest `scheduled_end` wins, ties broken by the latest `created_at`. When a predecessor exists and its formula's `allergen_class` differs from the confirming run's, the allergen changeover fee of 75000 cents applies; when the allergen classes match, or no predecessor exists at all, the standard fee of 15000 cents applies. Once locked, the fee is never recomputed — not even by later completions.

Material availability is then verified line by line. For each line of `packaging_requirements`, the requirement is the line's `quantity_per_unit` multiplied by `planned_units`, and the component's availability is its `on_hand_units` minus its `reserved_units`; a shortage exists only when the requirement strictly exceeds availability, so a requirement exactly equal to availability passes. Any shortage across the lines rejects the confirmation with `ERR_PACKAGING_SHORTAGE`. For each `CUSTOMER_SUPPLIED` ingredient line of the formula, `consigned_units_on_hand` must be at least `quantity_per_unit` multiplied by `planned_units`, with equality again permitted; any shortfall rejects the confirmation with `ERR_INGREDIENT_SHORTAGE`.

With availability proven, the estimated charge is computed. The units billed are the greater of `planned_units` and the formula's `min_run_units` — the contractual minimum run size is billed even when the plan is smaller. The base co-pack fee is those units billed multiplied by `unit_rate_cents`. Each `COPACKER_SUPPLIED` ingredient line contributes its `quantity_per_unit` multiplied by the units billed multiplied by its `unit_cost_cents`, rounded half-up to whole cents per line and then summed. Each packaging requirement line contributes its `quantity_per_unit` multiplied by the units billed multiplied by the component's `unit_cost_cents`, likewise rounded per line before summation. The `estimated_charge_cents` is the base plus the locked changeover fee plus the ingredient total plus the packaging total.

Only now does the credit gate apply: the customer's `outstanding_billed_cents` plus this `estimated_charge_cents` must not exceed `credit_limit_cents`. The breach test is strict — a sum exactly equal to the limit is permitted, and only a sum exceeding it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

A successful confirmation moves the run to `CONFIRMED`, bumps its `version`, and posts three sets of effects: the customer's `outstanding_billed_cents` increases by `estimated_charge_cents`; each packaging requirement reserves stock, raising the component's `reserved_units` by `quantity_per_unit` multiplied by `planned_units`; and each `CUSTOMER_SUPPLIED` line draws down consignment, reducing `consigned_units_on_hand` by the same per-line quantity.

Backing out is possible while a run is in `PLANNED` or `CONFIRMED`; against any other status the cancellation is rejected with `ERR_RUN_NOT_CANCELLABLE`. Cancelling a `PLANNED` run simply moves it to `CANCELLED`. Cancelling a `CONFIRMED` run unwinds everything confirmation posted: each component's `reserved_units` falls by its requirement, each consigned line's `consigned_units_on_hand` is restored by `quantity_per_unit` multiplied by `planned_units`, and the customer's `outstanding_billed_cents` is reduced by `estimated_charge_cents`. The same unwind, without any client call, is how reformulation disposes of `CONFIRMED` runs (§3.3). `CANCELLED` is terminal.

### 3.6. Run Completion: Final Billing and Automatic Quality Holds

Completion is recorded by an `OpsAdmin` against a run in `CONFIRMED` or `REWORK`; a run in any other status is rejected with `ERR_RUN_NOT_COMPLETABLE`. The call carries the production actuals: `actual_units_produced` (zero or more), `measured_ph`, and `measured_water_activity`. Before anything is booked, packaging feasibility is rechecked against actuals — for every requirement line, the component's `on_hand_units` must be at least `quantity_per_unit` multiplied by `actual_units_produced`, failing which the completion is rejected with `ERR_PACKAGING_SHORTAGE`.

The final charge mirrors the estimate with actuals substituted. The units billed are the greater of `actual_units_produced` and `min_run_units`; the base fee is those units multiplied by `unit_rate_cents`; the changeover fee is the value locked at confirmation, never recomputed. Ingredient lines extend against the units billed exactly as in the estimate — `quantity_per_unit` multiplied by the units billed multiplied by `unit_cost_cents`, rounded half-up per line then summed — while packaging lines extend against physical reality: `quantity_per_unit` multiplied by `actual_units_produced` multiplied by the component's `unit_cost_cents`, again rounded per line before summation. The result is stored as `final_charge_cents`. Billing then moves by the delta: the customer's `outstanding_billed_cents` increases by the final charge minus the previously applied charge, where "previously applied" means `estimated_charge_cents` on the first completion and the prior `final_charge_cents` on a re-completion after rework.

Physical stock moves with every completion. For each requirement line, `on_hand_units` falls by `quantity_per_unit` multiplied by `actual_units_produced` on every completion; the corresponding release of `reserved_units` by `quantity_per_unit` multiplied by `planned_units` happens on the first completion only, since the reservation is already zero by the time a rework re-completion runs.

Food-safety automation rides on the completion path. When the run's formula has an `ACTIVE` process-authority letter and the recorded measurements deviate from it — `measured_ph` exceeding the letter's `max_ph`, or `measured_water_activity` reaching or exceeding the letter's `max_water_activity` — the system does not let the run reach `COMPLETED`. Instead it creates a `QualityHold` whose `created_by_user_id` is the literal string `system`, whose measurements are copied from the completion call, and whose `reason_category` is `PH_DEVIATION` when the pH deviates, otherwise `AW_DEVIATION` (pH takes precedence when both deviate), and the run moves to `ON_HOLD` rather than `COMPLETED`. Absent any deviation — or absent any `ACTIVE` letter — the run simply moves to `COMPLETED`. Either way the run's `version` increments.

### 3.7. Quality Holds and Disposition

Beyond the automatic holds of completion, a `QAReviewer` may place a manual **QualityHold** on a run in `COMPLETED` or `ON_HOLD` — against any other run status the creation is rejected with `ERR_RUN_NOT_COMPLETED`. The hold names its `production_run_id`, a `reason_category` of `PH_DEVIATION`, `AW_DEVIATION`, `FOREIGN_MATERIAL`, or `LABEL_MISMATCH`, and the supporting evidence: `measured_ph` is required when the reason is `PH_DEVIATION`, and `measured_water_activity` when it is `AW_DEVIATION`, with a missing measurement rejected as `ERR_INVALID_REQUEST`. Creating the hold moves the run to `ON_HOLD` (a run already `ON_HOLD` stays there) and stamps `created_by_user_id` with the caller's `X-User-ID`. Every hold, manual or automatic, copies its `disposition_owner` from the owning customer's `default_disposition_owner` at creation, fixing who may later resolve it. Hold listings may be filtered by `production_run_id` and `status`.

Two deviation metrics are computed at hold creation, each rounded half-up to two decimal places. When the hold's reason is `PH_DEVIATION` and the formula has an `ACTIVE` letter, `letter_deviation` is the hold's `measured_ph` minus the letter's `max_ph`, and `statutory_margin` is 4.6 minus the measured pH. When the reason is `AW_DEVIATION` and a letter is active, `letter_deviation` is the measured water activity minus the letter's `max_water_activity`, and `statutory_margin` is 0.85 minus the measured water activity. For the other two reason categories — or whenever the formula has no `ACTIVE` letter at all — both metrics are null. A positive `letter_deviation` means the batch is over its contracted letter limit; a positive `statutory_margin` means the batch remains under the absolute statutory ceiling. The two deliberately disagree: a batch can be over its letter limit yet still under the statutory ceiling, and the metrics then differ in both value and sign.

Disposition resolves a hold, and it applies the pipeline of §2.7 in order. The hold must be `OPEN` (`ERR_HOLD_NOT_OPEN`). The statutory gate is evaluated before any actor check: a `RELEASE` or `REWORK` disposition on a `PH_DEVIATION` or `AW_DEVIATION` hold requires a strictly positive `statutory_margin` — without it the batch may only be destroyed, and the request is rejected with `ERR_STATUTORY_DESTROY_REQUIRED`. Only then come the actor rules. Owner routing enforces the hold's `disposition_owner`: a value of `CUSTOMER` requires a caller of role `Customer` whose `X-User-ID` equals the run's formula's `customer_id`, while `COPACKER` requires a `QAReviewer`; a mismatch is `ERR_DISPOSITION_OWNER_MISMATCH`. Segregation of duties then forbids self-resolution: the disposition caller's `X-User-ID` must differ from the hold's `created_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. The disposition itself carries a `disposition` of `RELEASE`, `REWORK`, or `DESTROY` plus an optional `disposition_note`; on success the hold becomes `DISPOSITIONED` with the choice recorded.

Each disposition drives the run differently. `RELEASE` returns the run from `ON_HOLD` to `COMPLETED`, but only once no other `OPEN` holds remain on that run — a release that leaves sibling holds open does not free the run. `REWORK` moves the run from `ON_HOLD` to `REWORK`, making it completable again under §3.6 with fresh actuals, a recomputed final charge, and a billing delta against the prior final. `DESTROY` moves the run from `ON_HOLD` to `DESTROYED`, and the system sweeps every other `OPEN` hold on that run into `DISPOSITIONED` with a `DESTROY` disposition of its own; because destroyed goods are not billable, the customer's `outstanding_billed_cents` is reduced by the run's `final_charge_cents`. `RELEASED`, `CANCELLED`, and `DESTROYED` are the terminal states of a run, and `DISPOSITIONED` is terminal for a hold.

### 3.8. Private-Label Approvals and Run Release

Private-label compliance is tracked per formula as **LabelApproval** records. An `OpsAdmin` or the owning `Customer` drafts one with the `formula_id`, a customer-supplied `label_version` tag, the `brand_display_name` to appear on pack, the `net_quantity_statement` of contents, and an `allergen_declaration` drawn from the same `NONE`, `GLUTEN`, `SOY`, `NUT`, `DAIRY` vocabulary as the formula's `allergen_class`. A draft label starts in `DRAFT`; label listings may be filtered by `formula_id` and `status`.

Submitting a draft — again `OpsAdmin` or the owning `Customer` — first requires the label to be in `DRAFT` (`ERR_LABEL_NOT_DRAFT`) and then, evaluated after the state gate, demands that `allergen_declaration` equal the formula's `allergen_class`; a declaration that disagrees with the recipe is rejected with `ERR_LABEL_ALLERGEN_MISMATCH`. A successful submission moves the label to `SUBMITTED`.

Review belongs to the `QAReviewer`. Acting on a label that is not `SUBMITTED` is rejected with `ERR_LABEL_NOT_SUBMITTED`. The review carries an `approved` flag and an optional `review_note`: approval moves the label to `APPROVED`, rejection to `REJECTED`, both terminal.

Release is the last gate a finished run passes, and it belongs to the `QAReviewer` alone. The run must be in `COMPLETED` (`ERR_RUN_NOT_COMPLETED`), no `OPEN` quality hold may reference it (`ERR_HOLD_BLOCKS_RELEASE`), and at least one label for the run's formula must have reached `APPROVED` (`ERR_LABEL_NOT_APPROVED`). A run that clears all three moves to `RELEASED` — shippable, billable, and done.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — state transitions, receipts, reviews, dispositions, confirmations, completions, and stock adjustments — return a `200 OK` status code. Request payloads, preconditions, and side effects are defined by the workflows in §3; the table below indexes only the method, path, and authorization of each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/copack/customers` | Create a customer (brand owner) account | OpsAdmin |
| GET | `/copack/customers/{id}` | Get a customer account | OpsAdmin, QAReviewer, Customer |
| POST | `/copack/formulas` | Intake a customer formula, created in `DRAFT` with `revision` 1 | OpsAdmin, Customer |
| GET | `/copack/formulas` | List formulas, filterable by customer and status | OpsAdmin, QAReviewer, Customer |
| GET | `/copack/formulas/{id}` | Get a formula | OpsAdmin, QAReviewer, Customer |
| PUT | `/copack/formulas/{id}` | Update a `DRAFT` formula's specification with optimistic concurrency | OpsAdmin, Customer |
| POST | `/copack/formulas/{id}/reformulate` | Return an `APPROVED` formula to `DRAFT`, superseding its letter and cancelling open runs | OpsAdmin, Customer |
| POST | `/copack/ingredient-supplies` | Add an ingredient line to a `DRAFT` formula | OpsAdmin, Customer |
| GET | `/copack/ingredient-supplies` | List ingredient supplies, filterable by formula | OpsAdmin, QAReviewer, Customer |
| GET | `/copack/ingredient-supplies/{id}` | Get an ingredient supply | OpsAdmin, QAReviewer, Customer |
| POST | `/copack/ingredient-supplies/{id}/receive` | Record a consignment receipt on a `CUSTOMER_SUPPLIED` line | OpsAdmin, Customer |
| POST | `/copack/pilot-cells` | Create a pilot plant cell | OpsAdmin |
| GET | `/copack/pilot-cells/{id}` | Get a pilot cell | OpsAdmin, QAReviewer |
| POST | `/copack/scale-up-trials` | Schedule a scale-up trial, moving the formula to `IN_TRIAL` | OpsAdmin |
| GET | `/copack/scale-up-trials` | List trials, filterable by formula and pilot cell | OpsAdmin, QAReviewer |
| GET | `/copack/scale-up-trials/{id}` | Get a trial | OpsAdmin, QAReviewer |
| POST | `/copack/scale-up-trials/{id}/record-results` | Record a trial's outcome, advancing or resetting the formula | OpsAdmin |
| POST | `/copack/scale-up-trials/{id}/cancel` | Cancel a `SCHEDULED` trial, returning the formula to `DRAFT` | OpsAdmin |
| POST | `/copack/process-authority-letters` | Submit a process authority letter for a trial-passed formula | ProcessAuthority |
| GET | `/copack/process-authority-letters` | List letters, filterable by formula | OpsAdmin, QAReviewer, ProcessAuthority, Customer |
| GET | `/copack/process-authority-letters/{id}` | Get a letter | OpsAdmin, QAReviewer, ProcessAuthority, Customer |
| POST | `/copack/process-authority-letters/{id}/activate` | Activate a `SUBMITTED` letter, superseding others and approving the formula | ProcessAuthority |
| POST | `/copack/kettle-lines` | Create a kettle/fill line | OpsAdmin |
| GET | `/copack/kettle-lines/{id}` | Get a kettle line | OpsAdmin, QAReviewer |
| POST | `/copack/packaging-components` | Create a packaging component with initial stock | OpsAdmin |
| GET | `/copack/packaging-components/{id}` | Get a packaging component | OpsAdmin, QAReviewer |
| PUT | `/copack/packaging-components/{id}` | Adjust `on_hand_units` with optimistic concurrency | OpsAdmin |
| POST | `/copack/production-runs` | Plan a production run, pinning the formula's current revision | OpsAdmin |
| GET | `/copack/production-runs` | List runs, filterable by formula, line, and status | OpsAdmin, QAReviewer, Customer |
| GET | `/copack/production-runs/{id}` | Get a production run | OpsAdmin, QAReviewer, Customer |
| POST | `/copack/production-runs/{id}/confirm` | Confirm a `PLANNED` run: lock fees, bill the estimate, reserve materials | OpsAdmin |
| POST | `/copack/production-runs/{id}/complete` | Complete a `CONFIRMED` or `REWORK` run with actuals; auto-hold on deviation | OpsAdmin |
| POST | `/copack/production-runs/{id}/release` | Release a `COMPLETED` run clear of holds with an approved label | QAReviewer |
| POST | `/copack/production-runs/{id}/cancel` | Cancel a `PLANNED` or `CONFIRMED` run, unwinding reservations and billing | OpsAdmin |
| POST | `/copack/quality-holds` | Place a manual quality hold on a `COMPLETED` or `ON_HOLD` run | QAReviewer |
| GET | `/copack/quality-holds` | List holds, filterable by run and status | OpsAdmin, QAReviewer, Customer |
| GET | `/copack/quality-holds/{id}` | Get a quality hold | OpsAdmin, QAReviewer, Customer |
| POST | `/copack/quality-holds/{id}/disposition` | Disposition an `OPEN` hold (`RELEASE`, `REWORK`, or `DESTROY`) | QAReviewer, Customer |
| POST | `/copack/label-approvals` | Draft a private-label approval for a formula | OpsAdmin, Customer |
| GET | `/copack/label-approvals` | List label approvals, filterable by formula and status | OpsAdmin, QAReviewer, Customer |
| GET | `/copack/label-approvals/{id}` | Get a label approval | OpsAdmin, QAReviewer, Customer |
| POST | `/copack/label-approvals/{id}/submit` | Submit a `DRAFT` label whose allergen declaration matches the formula | OpsAdmin, Customer |
| POST | `/copack/label-approvals/{id}/review` | QA review of a `SUBMITTED` label | QAReviewer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the workflow narratives of §2 and §3; this catalogue is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_FORMULA_NOT_FOUND` | 404 Not Found |
| `ERR_INGREDIENT_SUPPLY_NOT_FOUND` | 404 Not Found |
| `ERR_PILOT_CELL_NOT_FOUND` | 404 Not Found |
| `ERR_TRIAL_NOT_FOUND` | 404 Not Found |
| `ERR_LETTER_NOT_FOUND` | 404 Not Found |
| `ERR_KETTLE_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_COMPONENT_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_LABEL_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PROCESS_LIMITS` | 422 Unprocessable Entity |
| `ERR_LABEL_ALLERGEN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FORMULA_NOT_DRAFT` | 409 Conflict |
| `ERR_FORMULA_NOT_TRIAL_PASSED` | 409 Conflict |
| `ERR_FORMULA_NOT_APPROVED` | 409 Conflict |
| `ERR_TRIAL_NOT_SCHEDULED` | 409 Conflict |
| `ERR_LETTER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_LETTER_REVISION_STALE` | 409 Conflict |
| `ERR_RUN_NOT_PLANNED` | 409 Conflict |
| `ERR_RUN_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_RUN_NOT_COMPLETED` | 409 Conflict |
| `ERR_RUN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_HOLD_NOT_OPEN` | 409 Conflict |
| `ERR_HOLD_BLOCKS_RELEASE` | 409 Conflict |
| `ERR_LABEL_NOT_DRAFT` | 409 Conflict |
| `ERR_LABEL_NOT_SUBMITTED` | 409 Conflict |
| `ERR_LABEL_NOT_APPROVED` | 409 Conflict |
| `ERR_STATUTORY_DESTROY_REQUIRED` | 409 Conflict |
| `ERR_KETTLE_LINE_CONFLICT` | 409 Conflict |
| `ERR_PILOT_CELL_CONFLICT` | 409 Conflict |
| `ERR_PACKAGING_SHORTAGE` | 409 Conflict |
| `ERR_INGREDIENT_SHORTAGE` | 409 Conflict |
| `ERR_BATCH_EXCEEDS_CAPACITY` | 409 Conflict |
| `ERR_DISPOSITION_OWNER_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STOCK_BELOW_RESERVED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
