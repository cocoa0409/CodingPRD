# Medically-Tailored Meals API — Product Requirements Document

## 1. Introduction

Health plans and providers increasingly prescribe food as medicine: for members with renal disease, diabetes, or cardiac conditions, a steady supply of nutritionally appropriate meals is a clinical intervention with measurable outcomes. The Medically-Tailored Meals (MTM) platform exists to run that intervention end to end — from the moment a physician refers a member, through dietitian-authored diet prescriptions and weekly menu planning, to cold-chain-monitored home delivery, payer authorization, and final claims adjudication. All endpoints are mounted under the `/mtm` prefix.

This document specifies the product requirements for the MTM API. Two payer models are supported side by side — a Medicaid waiver program with income-tiered member cost sharing, and a Medicare Advantage supplemental benefit with a flat per-claim copay capped by an annual out-of-pocket maximum — and the platform must keep their fiscal ledgers, unit authorizations, and clinical compliance gates exactly reconciled at all times. Registered dietitians, care coordinators, logistics staff, drivers, billing specialists, and payer reviewers each own a segregated slice of the workflow, and the API enforces that segregation mechanically. Wherever the platform touches a member's health (allergens, nutrient ceilings, cold-chain spoilage) or a payer's money (authorizations, claims, remittances), the rules in this document are mandatory, not advisory.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Nine roles are recognized, spelled exactly as follows: `ProgramAdmin`, `CareCoordinator`, `ReferringProvider`, `Dietitian`, `LogisticsCoordinator`, `Driver`, `BillingSpecialist`, `PayerReviewer`, and `Member`. Each operation is restricted to designated roles; an authenticated user attempting an operation outside their role is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Header values are stripped of surrounding whitespace before these checks, and a whitespace-only value counts as empty. An `X-User-Role` value outside the nine recognized roles is permitted by no endpoint and is therefore always rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For `ProgramAdmin`, `CareCoordinator`, `ReferringProvider`, `Dietitian`, `LogisticsCoordinator`, `Driver`, `BillingSpecialist`, and `PayerReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `provider_user_id` on a submitted referral, as `dietitian_user_id` on a diet prescription or an outcome assessment, or as `submitted_by_user_id` on a submitted claim — but it does not compare these operator identifiers to any entity's `id`. The `Driver` role's identity is likewise opaque; a route merely records which driver operates it via its `driver_id`. When `X-User-Role` is `Member`, by contrast, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a member compare the resource's member foreign key to `X-User-ID`. This is what lets a member confirm receipt of their own delivery — and only their own.

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
- The `message` provides a human-readable explanation of what went wrong. A request to an undefined path is rejected with `ERR_NOT_FOUND` (HTTP 404); a request to a defined path with an unsupported method is rejected with `ERR_NOT_FOUND` carried by an HTTP 405 response; and any unexpected internal failure is reported as `ERR_INVALID_REQUEST`.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and filter parameters match by exact equality. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Most list endpoints additionally accept optional filter query parameters that narrow the result set: members filter by `status`; referrals by `member_id` and `status`; diet prescriptions by `member_id`, `referral_id`, `supersedes_id`, and `status`; menu items by `status`; menu cycles by `member_id`, `prescription_id`, and `status`; delivery routes by `driver_id`, `route_date`, and `status`; deliveries by `member_id`, `menu_cycle_id`, `route_id`, `authorization_id`, and `status`; reauthorizations by `member_id` and `status`; outcome assessments by `member_id`; and claims by `member_id`, `menu_cycle_id`, `authorization_id`, and `status`.

### 2.4. The Logical Clock and Expiry Sweeps

All date-sensitive business rules run on a server-maintained **logical clock**, never on wall-clock time. Before any clock-setting call has been made, the logical clock starts at exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time afterwards. A `ProgramAdmin` may advance the logical clock by supplying a `to_iso8601` timestamp; the capability responds with the resulting `current_utc`. The supplied `to_iso8601` is accepted as given — any valid ISO 8601 timestamp, with a missing offset read as UTC and no requirement that it move the clock forward — and the expiry sweep fires on every set. Only business semantics use the logical clock; the `created_at` and `updated_at` resource fields of §2.5 and the envelope's `api_request_timestamp` are generated from wall-clock time. Everywhere this document says "current logical date" — referral expiry, authorization windows, adherence windows, outcome-assessment recency — it means the date portion of this logical clock.

Advancing the logical clock fires an **expiry sweep** as a side effect. Any referral still sitting in `SUBMITTED` or `TRIAGED` whose `expires_at` date has been passed by the logical clock transitions automatically to `EXPIRED`. Any reauthorization in `APPROVED` status whose `end_date` has been passed transitions automatically to `EXPIRED`. Both are terminal.

### 2.5. Common Resource Properties

All primary resources — Member, Referral, DietPrescription, MenuItem, MenuCycle, DeliveryRoute, Delivery, Reauthorization, OutcomeAssessment, and Claim — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer initialized to 1 at creation that increments by one on every mutation, including mutations caused by cascades and by computed-ledger updates initiated from other resources.

Two sub-records are deliberately lighter: a **MenuCycleItem** line and a **ColdChainReading** carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these two resources, because neither is ever mutated after insertion.

### 2.6. Precision, Rounding, and Units

Money is always integer cents. No monetary field is ever a fractional value, and no rounding mode other than the one stated per calculation is permitted. Two rounding regimes exist. Adherence percentages are computed with round-half-up to 2 decimal places and reported as JSON numbers. Waiver cost-share calculations round each claim line's share half-up to whole cents *before* summing — the per-line-then-sum order is pinned, and the alternative sum-then-round order is expressly forbidden because it produces different cents. Cold-chain excursion durations are whole minutes produced by truncating any partial-minute remainder. Nutrient totals (milligrams of sodium, potassium, phosphorus; grams of carbohydrate and protein) are integers with no rounding at all.

### 2.7. Optimistic Concurrency Control

Two write operations mutate a parent aggregate whose `version` the client must prove it has observed; both enforce optimistic concurrency control.

The prescription activation endpoint (`POST /mtm/diet-prescriptions/{id}/activate`) requires a non-optional `expected_member_version` field carrying the member `version` the dietitian last read. Activation supersedes the member's currently `ACTIVE` prescription — a member-aggregate mutation — so if the member's current `version` has advanced beyond `expected_member_version`, the request is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), and the client must re-read the member and retry.

The claim creation endpoint (`POST /mtm/claims`) requires a non-optional `expected_reauthorization_version` field carrying the reauthorization `version` the billing specialist last read. Claim creation registers a fiscal liability against an authorization whose unit and amount ledgers move with every delivery and remittance, so if the authorization's current `version` has advanced beyond `expected_reauthorization_version`, the request is rejected with `ERR_STALE_AUTHORIZATION_VERSION` (HTTP 412), and the client must re-read the authorization and retry.

No other endpoint accepts a version field.

### 2.8. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed, global priority order so that the surfaced error is deterministic:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers must be present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization** — the declared role must be permitted for the endpoint (`ERR_UNAUTHORIZED_ROLE`, 403). A malformed body, a missing required field, a type mismatch, or an invalid enum or date value is a request-format failure reported as `ERR_INVALID_REQUEST` (400).
3. **Path existence** — every path identifier must resolve, validated left to right (`ERR_NOT_FOUND`, 404).
4. **Body reference existence** — foreign keys in the request body must resolve to existing resources (the resource-specific 404 errors such as `ERR_MEMBER_NOT_FOUND`; see §2.9).
5. **Optimistic concurrency** — `expected_member_version` and `expected_reauthorization_version` must match current versions (`ERR_STALE_MEMBER_VERSION` / `ERR_STALE_AUTHORIZATION_VERSION`, 412).
6. **State preconditions** — the target resource must be in a state that permits the operation (the family of 409 state errors).
7. **Safety checks** — allergen exposure is always evaluated before nutrition gates (`ERR_ALLERGEN_VIOLATION` before `ERR_NUTRITION_NON_COMPLIANT`, 422).
8. **Business constraints** — meal-count caps, segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403), and adherence thresholds (`ERR_ADHERENCE_BELOW_THRESHOLD`, 409).
9. **Temporal rules** — route window overlaps (`ERR_ROUTE_WINDOW_OVERLAP`, 409), prescription window overlaps (`ERR_PRESCRIPTION_WINDOW_OVERLAP`, 409), route-date agreement (`ERR_ROUTE_DATE_MISMATCH`, 422), authorization window coverage (`ERR_SERVICE_DATE_OUT_OF_AUTHORIZATION`, 422), and outcome-assessment recency (`ERR_OUTCOME_ASSESSMENT_STALE`, 409).
10. **Referential ownership** — cross-resource member alignment and member self-ownership (`ERR_PRESCRIPTION_MEMBER_MISMATCH`, `ERR_AUTHORIZATION_MEMBER_MISMATCH`, 422; `ERR_DELIVERY_NOT_OWNED`, 403).
11. **Fiscal limits** — checked last, so that a claim with both a wrong-state cycle and an over-budget amount reports the state problem first (`ERR_AUTHORIZATION_EXHAUSTED`, `ERR_AUTHORIZATION_AMOUNT_EXCEEDED`, 402).

### 2.9. Nested Resource and Body Reference Validation

For any path containing resource identifiers, the server validates each `{id}` segment in strict left-to-right order and rejects with `ERR_NOT_FOUND` (404) at the first segment that does not resolve — a request addressing an item line under a non-existent cycle fails on the cycle before the item-line identifier `itemId` in the `{itemId}` segment is ever examined. Separately, request bodies that reference other resources by foreign key are checked for existence with resource-specific 404 errors: `member_id` (`ERR_MEMBER_NOT_FOUND`), `referral_id` (`ERR_REFERRAL_NOT_FOUND`), `prescription_id` (`ERR_PRESCRIPTION_NOT_FOUND`), `menu_item_id` (`ERR_MENU_ITEM_NOT_FOUND`), `menu_cycle_id` (`ERR_MENU_CYCLE_NOT_FOUND`), `route_id` (`ERR_ROUTE_NOT_FOUND`), and `authorization_id` (`ERR_AUTHORIZATION_NOT_FOUND`).

### 2.10. Conserved Quantities: The Unit and Money Ledgers

Two quantities are conserved at all times, and every workflow in §3 is designed to preserve them. First, on every reauthorization, the number of authorized service units always equals the sum of used, reserved, and available units — deliveries move units between those buckets but never create or destroy them. Second, the money ledgers must reconcile exactly: a member's `oop_accumulator_cents` always equals the sum of `member_cost_share_cents` over that member's claims in `PAID` or `PARTIALLY_PAID`, and an authorization's `consumed_amount_cents` always equals the sum of `remitted_amount_cents` over that authorization's claims in `PAID` or `PARTIALLY_PAID`. A remittance followed by its void must leave both accumulators bit-identical to their pre-remittance values. Any ledger mutation bumps the owning resource's `version` and refreshes `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Enrolling and Managing Members

A `CareCoordinator` registers a new member by supplying `full_name`, `payer_type` (either `MEDICAID_WAIVER` or `MEDICARE_ADVANTAGE`), the payer-side identifier `payer_member_id`, the member's `allergies` (an array of allergen codes such as `PEANUT`, `SHELLFISH`, `DAIRY`, `GLUTEN`, `SOY`, or `EGG`), `income_fpl_percent` (household income as an integer percent of the federal poverty level, which later drives the waiver cost-share tier; any integer is accepted), and `household_size` (at least one). An optional `diagnosis_codes` array of ICD-10 codes may accompany registration; omitted, it defaults to an empty list. New members start in `INTAKE` status, with both adherence percentages initialized to 100.00 and `oop_accumulator_cents` at zero. A member's lifecycle states are `INTAKE`, `ACTIVE`, `SUSPENDED`, and `DISENROLLED`.

A `CareCoordinator` or `ProgramAdmin` drives status changes by posting a `target_status`. Activation moves `INTAKE` to `ACTIVE`; suspension moves `ACTIVE` to `SUSPENDED`; reactivation moves `SUSPENDED` back to `ACTIVE`, and this active-suspended loop may cycle indefinitely. Each transition increments the member's `version` by one. Disenrollment is terminal: from either `ACTIVE` or `SUSPENDED`, posting a `target_status` of `DISENROLLED` fires a three-link cascade. First, the member's `ACTIVE` diet prescription — if any — is revoked, moving it to `REVOKED`. Second, because that prescription mutation occurred, every one of the member's menu cycles in `PLANNED` or `FROZEN` whose `prescription_id` points at the now-revoked prescription is cancelled. Third, because each of those cycles was cancelled, every delivery of such a cycle in `SCHEDULED` or `OUT_FOR_DELIVERY` is cancelled too, and each cancelled delivery releases its reserved unit back onto its reauthorization. Attempting a status change on a `DISENROLLED` member is rejected with `ERR_MEMBER_TERMINAL`; any other state mismatch (for example, suspending an `INTAKE` member) is rejected with `ERR_INVALID_STATE`.

Reading a member returns the computed fields alongside the stored ones: `adherence_delivered_pct`, `adherence_confirmed_pct`, and `oop_accumulator_cents`. A dedicated member summary read packages `member_id`, `status`, both adherence variants, `oop_accumulator_cents`, and the `active_authorization_id` of the member's currently applicable approved authorization — when several `APPROVED` authorizations cover the current logical date, the applicable one is selected by the same waterfall as delivery scheduling (earliest `end_date`, ties broken by earlier `created_at`), and when none covers, `active_authorization_id` is null.

### 3.2. Referral Intake, Triage, and Expiry

Entry into the program begins when a `ReferringProvider` submits a referral containing `member_id`, the justifying `diagnosis_codes`, a `referred_diet_type` (one of `RENAL`, `DIABETIC`, `RENAL_DIABETIC`, or `CARDIAC`), and an `expires_at` ISO date. The server stamps the referral with the submitting operator's `provider_user_id` taken from `X-User-ID`, and the referral starts in `SUBMITTED` status.

A `CareCoordinator` works the queue by posting a `decision`. A decision of `TRIAGE` moves a `SUBMITTED` referral to `TRIAGED`. From `TRIAGED`, a decision of `ACCEPT` moves it to `ACCEPTED` — but only while the current logical date has not passed `expires_at`; if the referral's clock has run out, acceptance is rejected with `ERR_REFERRAL_EXPIRED`. A decision of `REJECT` moves a `TRIAGED` referral to `REJECTED`. Any decision attempted against a referral not in the required source state is rejected with `ERR_REFERRAL_NOT_ACTIONABLE`. Independently of human action, the logical-clock expiry sweep (§2.4) moves any lingering `SUBMITTED` or `TRIAGED` referral past its `expires_at` to `EXPIRED`. The remaining transition is machine-driven: when a diet prescription referencing an `ACCEPTED` referral is activated, the referral flips automatically to `CONSUMED`, marking that the referral has been used exactly once. `REJECTED`, `EXPIRED`, and `CONSUMED` are all terminal.

### 3.3. Authoring, Activating, and Superseding Diet Prescriptions

With an `ACCEPTED` referral in hand, a `Dietitian` drafts a diet prescription. The payload names the `member_id` and the `referral_id` it draws authority from, a `diet_type` (again one of `RENAL`, `DIABETIC`, `RENAL_DIABETIC`, `CARDIAC`), the nutrient envelope — `daily_sodium_mg_max`, `daily_potassium_mg_max` (relevant to renal diets), `daily_phosphorus_mg_max` (renal), `daily_carbs_g_max` (diabetic), and `daily_protein_g_min` as a floor rather than a ceiling — plus `excluded_allergens` (allergen codes the prescription rules out, unioned with the member's own `allergies` when menus are checked), a `meals_per_week` cap of at least one, and a closed effective window from `effective_from` through `effective_to`, both dates inclusive. The drafting operator is recorded as `dietitian_user_id`. The referenced referral must be `ACCEPTED` at drafting time, or the request is rejected with `ERR_REFERRAL_NOT_ACTIONABLE`; all five nutrient-envelope fields are required non-negative integers, and an `effective_to` earlier than `effective_from` is a request-format failure (`ERR_INVALID_REQUEST`). The referral must actually belong to the named member; a referral issued for someone else is rejected with `ERR_PRESCRIPTION_MEMBER_MISMATCH`. Two prescriptions of the same member that are both in `DRAFT` or `ACTIVE` may not have overlapping effective windows under closed-interval semantics — a shared boundary date already counts as an overlap — and a colliding draft is rejected with `ERR_PRESCRIPTION_WINDOW_OVERLAP`. A new prescription starts in `DRAFT` status.

Activation is the pivotal moment. A `Dietitian` activates a `DRAFT` prescription, supplying `expected_member_version` per §2.7. Activation requires the prescription to be `DRAFT` (otherwise `ERR_PRESCRIPTION_NOT_DRAFT`), the member to be `ACTIVE` (otherwise `ERR_MEMBER_NOT_ACTIVE`), and the referenced referral to be `ACCEPTED` (otherwise `ERR_REFERRAL_NOT_ACTIONABLE`). On success, several things happen as one transaction: the member's `version` increments by one; the referral moves to `CONSUMED`; every prior `ACTIVE` prescription of the member (at most one in practice), if any, moves to `SUPERSEDED`, and the newly activated prescription's `supersedes_id` is set to the most recently created superseded prescription's id (or remains null when there was none); and every menu cycle of the member still in `PLANNED` that was pinned to the superseded prescription is re-pinned to the newly `ACTIVE` prescription with its `compliance_status` reset to `UNCHECKED`. Cycles already `FROZEN` keep their original pin for the rest of their lives. A prescription that was itself superseded may later watch its own successor activate; the chain of `supersedes_id` values records the lineage.

A `Dietitian` may also revoke a prescription while it is `DRAFT` or `ACTIVE` (any other state draws `ERR_PRESCRIPTION_NOT_DRAFT`). Revoking a `DRAFT` prescription has no side effects. Revoking an `ACTIVE` one cascades: the member's `PLANNED` menu cycles pinned to that prescription move to `CANCELLED`, and their `SCHEDULED` deliveries move to `CANCELLED` with their reserved units released back to the corresponding reauthorizations. `SUPERSEDED` and `REVOKED` are terminal.

### 3.4. The Meal Catalog and Weekly Menu Cycle Compliance

A `ProgramAdmin` curates the meal catalog. Each catalog entry is created with a `name`, per-meal nutrient values `sodium_mg`, `potassium_mg`, `phosphorus_mg`, `carbs_g`, and `protein_g` (each a non-negative integer), the `allergen_codes` the meal contains, and an informational `base_cost_cents` catalog cost (a non-negative integer) — billing never uses this figure; it prices off the payer rate card instead. Catalog items start `ACTIVE` and may be retired; retiring an item that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`, and a retired item is terminal. Retired items remain visible through a reverse-reachability read that lists every cycle-item line referencing a given menu item.

Against an `ACTIVE` prescription, a `Dietitian` opens a weekly menu cycle by naming the `member_id`, the `prescription_id` (which must belong to that member and be `ACTIVE`, otherwise `ERR_PRESCRIPTION_NOT_ACTIVE`), and the `week_start_date`. The cycle starts `PLANNED` with `compliance_status` `UNCHECKED` and `meals_count` zero. While `PLANNED`, the dietitian adds item lines, each naming a `menu_item_id` and a `quantity` of at least one, and may remove lines again; adding to a cycle that is not `PLANNED` is rejected with `ERR_MENU_CYCLE_NOT_PLANNED`, and adding a `RETIRED` item is rejected with `ERR_MENU_ITEM_RETIRED`. Every add or remove recomputes `meals_count` as the sum of `quantity` across the cycle's lines.

Freezing is the compliance gate. A `Dietitian` freezes a `PLANNED` cycle; the request is rejected with `ERR_MENU_CYCLE_NOT_PLANNED` if the cycle is in any other state, with `ERR_MEMBER_NOT_ACTIVE` if the member is not `ACTIVE`, and with `ERR_PRESCRIPTION_NOT_ACTIVE` if the pinned prescription is no longer `ACTIVE`. The safety checks then run in a fixed order. First, allergen exposure: the blocked set is the union of the member's `allergies` and the pinned prescription's `excluded_allergens`, and if any item line's `allergen_codes` intersect that set the freeze is rejected with `ERR_ALLERGEN_VIOLATION`. Second, nutrition gates: weekly totals are computed by summing, across all item lines, each meal's nutrient value multiplied by its line `quantity`; each weekly limit is seven times the prescription's corresponding daily limit, since a cycle spans a seven-day week. Which gates apply depends on the pinned prescription's `diet_type`: a `RENAL` prescription enforces the sodium, potassium, and phosphorus ceilings plus the protein floor; `DIABETIC` enforces sodium, carbohydrate, and protein; `RENAL_DIABETIC` enforces all five gates; `CARDIAC` enforces sodium and protein only. A ceiling gate passes when its weekly total is no more than seven times the daily maximum; the protein gate passes when the weekly protein total is at least seven times `daily_protein_g_min`. Any failed gate rejects the freeze with `ERR_NUTRITION_NON_COMPLIANT`. Third, the meal-count cap: if `meals_count` exceeds the prescription's `meals_per_week`, the freeze is rejected with `ERR_MEAL_COUNT_EXCEEDED`. A successful freeze moves the cycle to `FROZEN`, sets `compliance_status` to `PASSED`, and locks the `prescription_id` pin for the life of the cycle.

A read-only compliance view recomputes the same arithmetic on demand for any cycle regardless of status, reporting `sodium_mg_total`, `potassium_mg_total`, `phosphorus_mg_total`, `carbs_g_total`, `protein_g_total`, `meals_count`, the `allergen_violations` (one entry per offending item line, each entry the line's item name, sorted by item name ascending with ties broken by the line's `created_at` ascending), the `nutrient_violations` (one entry per failed gate, a lowercase identifier drawn from `sodium`, `potassium`, `phosphorus`, `carbs`, and `protein` and listed in that fixed order), and the two booleans `nutrition_compliant` and `allergen_ok`.

Revision is possible but guarded. Unfreezing returns a `FROZEN` cycle to `PLANNED` and resets `compliance_status` to `UNCHECKED`, but only while no delivery of the cycle is `SCHEDULED` or `OUT_FOR_DELIVERY`; open deliveries block the unfreeze with `ERR_MENU_CYCLE_HAS_OPEN_DELIVERIES`, and a cycle that is not `FROZEN` draws `ERR_MENU_CYCLE_NOT_FROZEN`. This planned-frozen-planned loop may repeat. Cancelling is allowed from `PLANNED` or `FROZEN` (a `FULFILLED` or already-`CANCELLED` cycle draws `ERR_MENU_CYCLE_TERMINAL`) and moves the cycle to `CANCELLED`, cancels every delivery of the cycle still in `SCHEDULED` or `OUT_FOR_DELIVERY`, and releases each cancelled delivery's reserved unit. Finally, a `FROZEN` cycle is fulfilled automatically the moment it has at least one `DELIVERED` delivery and every one of its deliveries sits in a terminal state (`DELIVERED`, `FAILED`, `CANCELLED`, or `SPOILED`), moving it to `FULFILLED`.

### 3.5. Routes, Deliveries, and the Cold Chain

Logistics begins with routes. A `LogisticsCoordinator` creates a delivery route with a `driver_id`, a `route_date`, a half-open time window from `start_time` (inclusive) to `end_time` (exclusive, and required to be strictly after the start — both times are given in `HH:MM` 24-hour format, and an `end_time` not strictly after `start_time` is a request-format failure, `ERR_INVALID_REQUEST`), and a `capacity_stops` of at least one. For the same driver on the same date, windows of non-terminal routes must not overlap under half-open semantics — back-to-back windows that merely touch are allowed, since the end boundary is exclusive — and a colliding route is rejected with `ERR_ROUTE_WINDOW_OVERLAP`. Routes start `PLANNED`. Dispatch moves a `PLANNED` route to `DISPATCHED` (any other state draws `ERR_INVALID_STATE`). Completion moves a `DISPATCHED` route to `COMPLETED`, but only once every delivery on the route has reached a terminal state; open deliveries block completion with `ERR_ROUTE_HAS_OPEN_DELIVERIES`, and completing a route that was never dispatched draws `ERR_ROUTE_NOT_DISPATCHED`.

Scheduling a delivery is a `LogisticsCoordinator` action that threads several constraints together. The payload carries `member_id`, `menu_cycle_id`, `route_id`, and `service_date`. The cycle must be `FROZEN` (otherwise `ERR_MENU_CYCLE_NOT_FROZEN`) and the route must be `PLANNED` or `DISPATCHED` (any other route state draws `ERR_INVALID_STATE`). The `service_date` must equal the route's `route_date` exactly, otherwise `ERR_ROUTE_DATE_MISMATCH`. The scheduler then reserves one service unit from the member's authorizations by waterfall: among the member's reauthorizations in `APPROVED` status whose window covers the `service_date` on both ends inclusive and that still have at least one available unit, the one with the earliest `end_date` wins, with ties broken by earlier `created_at`. If no approved authorization's window covers the service date at all, scheduling is rejected with `ERR_SERVICE_DATE_OUT_OF_AUTHORIZATION`; if covering authorizations exist but every one is out of available units, the rejection is the fiscal `ERR_AUTHORIZATION_EXHAUSTED` (HTTP 402). On success the selected authorization's `reserved_units` increases by one (bumping its `version`), the delivery records the winning `authorization_id`, and the delivery starts in `SCHEDULED` with `cold_chain_status` `INTACT` — two parallel state dimensions that evolve independently from here.

The `Driver` takes over in the field. Marking a delivery out for delivery moves it from `SCHEDULED` to `OUT_FOR_DELIVERY` and requires the route to be `DISPATCHED` (a delivery not in `SCHEDULED` is rejected first with `ERR_DELIVERY_NOT_SCHEDULED`; the route check then draws `ERR_ROUTE_NOT_DISPATCHED`). Marking it delivered requires `OUT_FOR_DELIVERY` (otherwise `ERR_DELIVERY_NOT_OUT_FOR_DELIVERY`) and is refused with `ERR_DELIVERY_TERMINAL` if the cold chain has already spoiled the parcel. A successful delivery stamps `delivered_at` from the logical clock and settles the reserved unit: the authorization's `reserved_units` decreases by one and its `used_units` increases by one, with a `version` bump; if `used_units` thereby reaches `authorized_units`, the authorization flips automatically to `EXHAUSTED`. If the delivery's cycle now has all deliveries terminal with at least one `DELIVERED`, the cycle flips automatically to `FULFILLED`. Marking a delivery failed — again only from `OUT_FOR_DELIVERY` — performs the compensating release: `reserved_units` decreases by one (with a `version` bump), no unit is consumed, and the same automatic cycle-fulfillment check runs. Cancellations arrive only through cascades (cycle cancel or member disenrollment) and likewise release the reserved unit.

While a delivery is `OUT_FOR_DELIVERY`, the `Driver` appends cold-chain readings, each stamped with its parent `delivery_id` and carrying a `recorded_at` timestamp and a `temp_celsius` sample; appending to a delivery in any other status is rejected with `ERR_DELIVERY_NOT_OUT_FOR_DELIVERY`. After every inserted reading the server replays the delivery's readings sorted by `recorded_at` ascending with ties broken by `created_at` ascending — insertion order may differ from recorded order, and the sorted order governs. For each reading strictly above 8.0 degrees Celsius that has a successor reading, the gap to that successor accrues toward `cumulative_excursion_minutes` in whole minutes, truncating any seconds; the final reading accrues nothing. The `cold_chain_status` dimension then re-derives: `INTACT` when no reading exceeds 8.0 degrees; `EXCURSION` when at least one does but cumulative excursion is at most 30 minutes; `SPOILED` when cumulative excursion is strictly greater than 30 minutes — exactly 30 is not spoiled. An `EXCURSION` does not block marking the delivery `DELIVERED`, but a transition of `cold_chain_status` to `SPOILED` forces the delivery's own `status` to `SPOILED` and releases its reserved unit with the usual authorization `version` bump. Readings remain retrievable in chronological order (`recorded_at` ascending, ties by `created_at` ascending).

The last mile closes with the member. A `Member` confirms receipt of a `DELIVERED` delivery, which stamps `confirmed_at` from the logical clock and feeds the confirmed-based adherence variant. Confirming a delivery that is not `DELIVERED` is rejected with `ERR_INVALID_STATE`, a check that runs before ownership. Because member identity is entity-backed (§2.1), the delivery's `member_id` must equal the caller's `X-User-ID`; confirming someone else's delivery is rejected with `ERR_DELIVERY_NOT_OWNED` (HTTP 403). Confirming an already-confirmed delivery succeeds again and simply refreshes `confirmed_at`.

### 3.6. Reauthorization, Adherence, and Outcome Review

Payer coverage is time-boxed and must be renewed. A `CareCoordinator` requests a reauthorization with `member_id`, the number of delivery service units sought (`authorized_units`, at least one), a `max_amount_cents` ceiling on plan-paid spend over the window (a non-negative integer), and a window from `start_date` through `end_date`, both inclusive (an `end_date` earlier than `start_date` is a request-format failure, `ERR_INVALID_REQUEST`). The request starts `PENDING` with `used_units`, `reserved_units`, and `consumed_amount_cents` all at zero; `available_units` is always the authorized units minus used minus reserved, per the conservation invariant of §2.10.

A `PayerReviewer` adjudicates. Approval requires the reauthorization to be `PENDING` (otherwise `ERR_AUTHORIZATION_NOT_PENDING`), the member not to be `DISENROLLED` (otherwise `ERR_MEMBER_TERMINAL`), and two clinical-governance gates. The member's `adherence_delivered_pct` must be at least 80.00; a member below that floor is rejected with `ERR_ADHERENCE_BELOW_THRESHOLD`. And the member must have an outcome assessment whose `assessed_at` is on or after the date 90 days before the current logical date (no upper bound is applied, so a future-dated assessment also qualifies); without one, approval is rejected with `ERR_OUTCOME_ASSESSMENT_STALE`. A successful approval records the payer's `authorization_number` from the request, moves the reauthorization to `APPROVED`, and increments its `version`. Denial simply requires `PENDING` status, accepts an optional free-text `reason` (validated as a string when present and not persisted), and lands in `DENIED`. From `APPROVED`, two automatic exits exist: exhaustion when `used_units` reaches `authorized_units` (§3.5), and expiry when the logical-clock sweep passes `end_date` (§2.4). `DENIED`, `EXHAUSTED`, and `EXPIRED` are terminal.

Both adherence percentages derive from the member's deliveries whose `service_date` falls inside the window running from 84 days before the current logical date through the current logical date, both ends inclusive. The delivered-based variant divides the count of `DELIVERED` deliveries by the count of deliveries in `DELIVERED`, `FAILED`, or `SPOILED`, multiplies by 100, and rounds half-up to two decimals; when that denominator is zero the value is 100.00. The confirmed-based variant divides the count of `DELIVERED` deliveries with a non-null `confirmed_at` by the count of `DELIVERED` deliveries only — same window, different numerator and denominator — again at 100.00 when no `DELIVERED` deliveries exist. Because the two variants use different denominators they genuinely diverge: four delivered and one failed delivery with three confirmations yields 80.00 delivered-based but 75.00 confirmed-based. The delivered-based variant gates reauthorization approval; both variants appear on the member read and the member summary.

Outcome assessments themselves are recorded by a `Dietitian` with `member_id`, the `assessed_at` date, measured `weight_kg` and `hba1c_pct`, and optional `notes`; the assessing operator is stamped as `dietitian_user_id`.

### 3.7. Claims, Remittance, and Fiscal Reconciliation

Once meals have been delivered, a `BillingSpecialist` opens a claim. The payload names the `member_id`, the `menu_cycle_id`, and the `authorization_id` to bill, plus `expected_reauthorization_version` per §2.7. The cycle must be `FROZEN` or `FULFILLED` with at least one `DELIVERED` delivery (otherwise `ERR_MENU_CYCLE_NOT_FROZEN`), and the authorization must belong to the same member as the claim (otherwise `ERR_AUTHORIZATION_MEMBER_MISMATCH`). Creation snapshots the member's `payer_type` into `payer_type_snapshot`, sets `units_delivered` to the cycle's `meals_count` at that moment, computes the provisional amounts below, increments the authorization's `version` by one, and lands the claim in `DRAFT`.

Provisional pricing runs off the payer rate card, not the catalog. The per-meal rate is 925 cents when `payer_type_snapshot` is `MEDICAID_WAIVER` and 1180 cents for `MEDICARE_ADVANTAGE`. Each item line's gross is the rate multiplied by its `quantity`, and `provisional_gross_cents` is the sum of those line grosses. The member's cost share then depends on payer type. Under the waiver, the member's `income_fpl_percent` selects a tier: below 138 the share is zero percent; at least 138 and at most 150 the share is five percent; above 150 the share is ten percent. Each line's share is that tier percentage of the line gross, rounded half-up to whole cents per line first, and `member_cost_share_cents` is the sum of those per-line amounts — rounding after summing is forbidden because it yields different cents (two 925-cent lines at the five-percent tier give 46 plus 46, that is 92 cents per-line, versus 93 cents if the sum were rounded once). Under Medicare Advantage, the cost share is a flat copay of 500 cents capped by annual out-of-pocket headroom: `member_cost_share_cents` is the lesser of 500 and the member's remaining headroom, where headroom is 34000 cents minus the member's current `oop_accumulator_cents`, floored at zero. Either way, `plan_liability_cents` is the provisional gross minus the cost share. These figures are the claim's provisional variant; the final variant is the adjudicated `remitted_amount_cents` recorded at remittance, and a fully paid claim remits exactly `plan_liability_cents`, which differs from `provisional_gross_cents` whenever the cost share is non-zero.

Submission is gated in a deliberate order. A `BillingSpecialist` submits a `DRAFT` claim (any other status draws `ERR_CLAIM_NOT_DRAFT`). The cycle's state is checked first — it must be `FROZEN` or `FULFILLED`, else `ERR_MENU_CYCLE_NOT_FROZEN` — then the authorization must be `APPROVED` (otherwise `ERR_AUTHORIZATION_NOT_APPROVED`), and only then the fiscal headroom: the claim's `provisional_gross_cents` must not exceed the authorization's remaining amount, which is `max_amount_cents` minus `consumed_amount_cents`; overage is rejected with `ERR_AUTHORIZATION_AMOUNT_EXCEEDED` (HTTP 402). A successful submission stamps `submitted_by_user_id` from `X-User-ID` and moves the claim to `SUBMITTED`.

Adjudication belongs to the `PayerReviewer`, who remits with an `outcome`. All remittances require a `SUBMITTED` claim (otherwise `ERR_CLAIM_NOT_SUBMITTED`). An outcome of `PAID` requires `remitted_amount_cents` to equal `plan_liability_cents` exactly; `PARTIALLY_PAID` requires a remitted amount strictly greater than zero and strictly less than `plan_liability_cents`; `DENIED` requires the amount to be omitted or zero. Any other combination is rejected with `ERR_REMIT_AMOUNT_MISMATCH`. A paid or partially paid remittance moves money onto the ledgers: the member's `oop_accumulator_cents` increases by the claim's `member_cost_share_cents`, and the authorization's `consumed_amount_cents` increases by `remitted_amount_cents` with a `version` bump. A denied claim is not dead: a `BillingSpecialist` may correct a `DENIED` claim back to `DRAFT` (otherwise `ERR_CLAIM_NOT_DENIED`), and the draft-submitted-denied-draft loop may repeat.

Voiding unwinds money, under segregation of duties. A `BillingSpecialist` may void a claim in `PAID` or `PARTIALLY_PAID` (any other status draws `ERR_CLAIM_NOT_VOIDABLE`), but the operator voiding must not be the operator who submitted: if the caller's `X-User-ID` equals the claim's `submitted_by_user_id`, the void is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful void performs the compensating reversal — the member's `oop_accumulator_cents` decreases by the claim's `member_cost_share_cents`, and the authorization's `consumed_amount_cents` decreases by `remitted_amount_cents` with a `version` bump — restoring both accumulators exactly per §2.10. `PAID`, `PARTIALLY_PAID`, and `VOIDED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The single removal operation — deleting an item line from a menu cycle — returns `204 No Content` with no body. All endpoints are mounted under `/mtm` and follow the envelope, pagination, and validation rules of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mtm/_clock/set_current_utc` | Set the server logical clock; fires the expiry sweep | ProgramAdmin |
| POST | `/mtm/members` | Register a member (starts INTAKE) | CareCoordinator |
| GET | `/mtm/members` | List members | Any |
| GET | `/mtm/members/{id}` | Get a member including computed adherence and OOP fields | Any |
| POST | `/mtm/members/{id}/status` | Transition member status; disenrollment fires the depth-3 cascade | CareCoordinator, ProgramAdmin |
| GET | `/mtm/members/{id}/summary` | Computed read: adherence variants, OOP accumulator, active authorization | Any |
| POST | `/mtm/referrals` | Submit a referral (starts SUBMITTED) | ReferringProvider |
| GET | `/mtm/referrals` | List referrals | Any |
| GET | `/mtm/referrals/{id}` | Get a referral | Any |
| POST | `/mtm/referrals/{id}/decision` | Triage, accept, or reject a referral | CareCoordinator |
| POST | `/mtm/diet-prescriptions` | Create a DRAFT prescription against an ACCEPTED referral | Dietitian |
| GET | `/mtm/diet-prescriptions` | List diet prescriptions | Any |
| GET | `/mtm/diet-prescriptions/{id}` | Get a diet prescription | Any |
| POST | `/mtm/diet-prescriptions/{id}/activate` | Activate a DRAFT prescription (OCC on member version); supersedes prior ACTIVE and re-pins PLANNED cycles | Dietitian |
| POST | `/mtm/diet-prescriptions/{id}/revoke` | Revoke a DRAFT or ACTIVE prescription | Dietitian |
| POST | `/mtm/menu-items` | Create a catalog meal | ProgramAdmin |
| GET | `/mtm/menu-items` | List menu items | Any |
| GET | `/mtm/menu-items/{id}` | Get a menu item | Any |
| POST | `/mtm/menu-items/{id}/retire` | Retire a menu item | ProgramAdmin |
| GET | `/mtm/menu-items/{id}/menu-cycle-items` | List cycle-item lines referencing this menu item | Any |
| POST | `/mtm/menu-cycles` | Create a weekly cycle pinned to an ACTIVE prescription | Dietitian |
| GET | `/mtm/menu-cycles` | List menu cycles | Any |
| GET | `/mtm/menu-cycles/{id}` | Get a menu cycle | Any |
| GET | `/mtm/menu-cycles/{id}/items` | List the cycle's item lines | Any |
| POST | `/mtm/menu-cycles/{id}/items` | Add an item line (cycle PLANNED; item not RETIRED) | Dietitian |
| DELETE | `/mtm/menu-cycles/{id}/items/{itemId}` | Remove an item line (cycle PLANNED) | Dietitian |
| GET | `/mtm/menu-cycles/{id}/compliance` | Computed read: weekly nutrient totals, allergen violations, compliance verdict | Any |
| POST | `/mtm/menu-cycles/{id}/freeze` | Freeze the cycle after allergen, nutrition, and meal-count gates | Dietitian |
| POST | `/mtm/menu-cycles/{id}/unfreeze` | Return a FROZEN cycle to PLANNED (no open deliveries) | Dietitian |
| POST | `/mtm/menu-cycles/{id}/cancel` | Cancel a PLANNED or FROZEN cycle; cancels open deliveries and releases units | Dietitian |
| POST | `/mtm/delivery-routes` | Create a route; same driver+date windows may not overlap (adjacency allowed) | LogisticsCoordinator |
| GET | `/mtm/delivery-routes` | List routes | Any |
| GET | `/mtm/delivery-routes/{id}` | Get a route | Any |
| POST | `/mtm/delivery-routes/{id}/dispatch` | Dispatch a PLANNED route | LogisticsCoordinator |
| POST | `/mtm/delivery-routes/{id}/complete` | Complete a DISPATCHED route once all deliveries are terminal | LogisticsCoordinator |
| POST | `/mtm/deliveries` | Schedule a delivery; waterfall unit reservation on APPROVED authorizations | LogisticsCoordinator |
| GET | `/mtm/deliveries` | List deliveries | Any |
| GET | `/mtm/deliveries/{id}` | Get a delivery | Any |
| POST | `/mtm/deliveries/{id}/out-for-delivery` | Driver picks up the parcel (route must be DISPATCHED) | Driver |
| POST | `/mtm/deliveries/{id}/mark-delivered` | Mark delivered: consumes a unit; may exhaust authorization and fulfill cycle | Driver |
| POST | `/mtm/deliveries/{id}/mark-failed` | Mark failed: releases the reserved unit | Driver |
| POST | `/mtm/deliveries/{id}/confirm-receipt` | Member confirms receipt of own DELIVERED delivery | Member |
| POST | `/mtm/deliveries/{id}/cold-chain-readings` | Append a temperature reading; may spoil the delivery | Driver |
| GET | `/mtm/deliveries/{id}/cold-chain-readings` | List a delivery's readings in chronological order | Any |
| POST | `/mtm/reauthorizations` | Request a payer reauthorization (starts PENDING) | CareCoordinator |
| GET | `/mtm/reauthorizations` | List reauthorizations | Any |
| GET | `/mtm/reauthorizations/{id}` | Get a reauthorization (used/reserved/available units, consumed amount) | Any |
| POST | `/mtm/reauthorizations/{id}/approve` | Approve: adherence at least 80.00 and an outcome assessment within 90 days | PayerReviewer |
| POST | `/mtm/reauthorizations/{id}/deny` | Deny a PENDING reauthorization | PayerReviewer |
| POST | `/mtm/outcome-assessments` | Dietitian records an outcome assessment | Dietitian |
| GET | `/mtm/outcome-assessments` | List outcome assessments | Any |
| GET | `/mtm/outcome-assessments/{id}` | Get an outcome assessment | Any |
| POST | `/mtm/claims` | Create a DRAFT claim (OCC on authorization version); computes provisional amounts | BillingSpecialist |
| GET | `/mtm/claims` | List claims | Any |
| GET | `/mtm/claims/{id}` | Get a claim | Any |
| POST | `/mtm/claims/{id}/submit` | Submit a DRAFT claim (cycle state, then authorization state, then fiscal headroom) | BillingSpecialist |
| POST | `/mtm/claims/{id}/remit` | Payer adjudication: PAID, PARTIALLY_PAID, or DENIED | PayerReviewer |
| POST | `/mtm/claims/{id}/correct` | Return a DENIED claim to DRAFT | BillingSpecialist |
| POST | `/mtm/claims/{id}/void` | Void a PAID/PARTIALLY_PAID claim; segregated from the submitter; reverses ledgers | BillingSpecialist |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_DELIVERY_NOT_OWNED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_MEMBER_TERMINAL` | 409 Conflict |
| `ERR_REFERRAL_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_REFERRAL_EXPIRED` | 409 Conflict |
| `ERR_PRESCRIPTION_NOT_DRAFT` | 409 Conflict |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRESCRIPTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_MENU_CYCLE_NOT_PLANNED` | 409 Conflict |
| `ERR_MENU_CYCLE_NOT_FROZEN` | 409 Conflict |
| `ERR_MENU_CYCLE_TERMINAL` | 409 Conflict |
| `ERR_MENU_CYCLE_HAS_OPEN_DELIVERIES` | 409 Conflict |
| `ERR_MENU_ITEM_RETIRED` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_HAS_OPEN_DELIVERIES` | 409 Conflict |
| `ERR_ROUTE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DELIVERY_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DELIVERY_NOT_OUT_FOR_DELIVERY` | 409 Conflict |
| `ERR_DELIVERY_TERMINAL` | 409 Conflict |
| `ERR_CLAIM_NOT_DRAFT` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_DENIED` | 409 Conflict |
| `ERR_CLAIM_NOT_VOIDABLE` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_PENDING` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_APPROVED` | 409 Conflict |
| `ERR_ADHERENCE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_OUTCOME_ASSESSMENT_STALE` | 409 Conflict |
| `ERR_STALE_MEMBER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AUTHORIZATION_VERSION` | 412 Precondition Failed |
| `ERR_PRESCRIPTION_MEMBER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AUTHORIZATION_MEMBER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ROUTE_DATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SERVICE_DATE_OUT_OF_AUTHORIZATION` | 422 Unprocessable Entity |
| `ERR_ALLERGEN_VIOLATION` | 422 Unprocessable Entity |
| `ERR_NUTRITION_NON_COMPLIANT` | 422 Unprocessable Entity |
| `ERR_MEAL_COUNT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_REMIT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AUTHORIZATION_EXHAUSTED` | 402 Payment Required |
| `ERR_AUTHORIZATION_AMOUNT_EXCEEDED` | 402 Payment Required |
