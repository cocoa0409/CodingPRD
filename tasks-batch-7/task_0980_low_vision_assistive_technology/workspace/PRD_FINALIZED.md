# Low-Vision & Assistive-Technology Service API — Product Requirements Document

## 1. Introduction

A low-vision clinic does far more than hand a patient a magnifier. The care pathway begins with a referral from a physician, a vocational-rehabilitation agency, an insurer, or the patient themselves; proceeds through a structured clinical evaluation that recommends a device category; moves into device fulfillment — outright purchase, a time-boxed home trial, or a no-charge loaner; and continues through training sessions, subscription software support, repair and rework, and finally a measurable outcome assessment. Running alongside that clinical spine is a funding spine: vocational-rehabilitation vouchers and insurance authorizations reserve money, claims draw against those reservations, adjudicators approve or deny them, and segregation-of-duties rules keep the person who submitted a request from also deciding it.

This document specifies the REST API that supports that service end to end. It is written for the engineer implementing the server: every behavioral rule is stated here in prose, while the structural contract — envelope shape, pagination, error catalogue, endpoint table — is stated in the precise sections. Two cross-cutting design decisions color everything that follows. First, the system runs on a **logical clock** that can be advanced for test-driving and scheduled processing; trial expiry, loan overdue detection, subscription past-due transitions, and funding-window expiry are all evaluated against this clock rather than wall-clock time. Second, money is tracked as integer cents with deterministic rounding, because funding reconciliation tolerates no drift: a claim reservation that does not exactly match its release would silently corrupt an authorization's remaining balance.

The readership should note one deliberate stylistic choice: §3 describes workflows in business language without naming URLs; §4 provides the definitive method-and-path table. When §3 says "converting a trial," §4 is where the reader learns which HTTP call performs it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user, and `X-User-Role` naming the capacity in which they act. If either header is missing, or the role value is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). This authorization check runs before any business logic — a well-formed request from the wrong role never reaches a state machine.

Seven roles are recognized, spelled exactly as follows:

- `IntakeCoordinator` — front-desk intake staff; registers clients and referrals and decides each referral's fate.
- `VisionSpecialist` — the low-vision clinician; owns evaluations, device orders, training plans and sessions, and outcome assessments, and may receive returned loaned equipment.
- `FundingCoordinator` — the funding case worker; drafts, submits, and appeals funding authorizations.
- `PayerAdjudicator` — the external payer side (VR counselor or insurance adjudicator); adjudicates authorizations and claims.
- `BillingSpecialist` — billing staff; owns the claim lifecycle and subscription billing.
- `RepairTechnician` — the bench technician; opens and advances repair tickets and receives returned loaned equipment.
- `ClinicAdmin` — clinic administrator; owns the device catalog, physical stock, the daily operations sweep, and the test-driving clock.

For **every** role in this system, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for attribution — for example as `evaluator_user_id` on an Evaluation, `technician_user_id` on a RepairTicket, `submitted_by_user_id` on a FundingAuthorization or Claim, `adjudicated_by_user_id` on a FundingAuthorization, or as the `instructor_user_id` supplied when scheduling a TrainingSession — but it never compares `X-User-ID` against any entity's `id` for ownership. The one place `X-User-ID` is compared against anything is the segregation-of-duties rule described in §2.8.

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

List endpoints accept two query parameters. `limit` caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless a more specific rule is stated, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Catalog Counter Invariant

Every top-level resource — Client, Referral, Evaluation, DeviceModel, DeviceUnit, DeviceOrder, LoanAgreement, TrainingPlan, TrainingSession, FundingAuthorization, Claim, RepairTicket, Subscription, OutcomeAssessment — carries a standard set of system-managed properties:

- `id` — a server-minted UUID with no type prefix; it serves identity only and is never an input to any business decision or ranking rule.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on **every** mutation of the resource, including mutations caused by a cascaded side effect from another resource's transition.
- `version` — an integer starting at 1 at creation and incremented by exactly 1 on every mutation, again including cascaded ones. When one API call mutates several resources (as the repair-loaner cascade does), each touched resource independently refreshes its `updated_at` and increments its `version`.

Two integer counters live on every DeviceModel and are recomputed on each DeviceUnit status change: `in_stock_count` is the number of units of that model currently in `IN_STOCK` status, and `total_count` is the number of units of that model across **every** status, including `RETIRED`. The conservation law is that `total_count` changes only when a new unit is received into stock — allocating, loaning, repairing, returning, or retiring a unit merely shifts it between status buckets. When a unit is received, both counters increment; when a unit leaves `IN_STOCK` (allocation, loan, repair start, retirement) `in_stock_count` decrements; when a unit returns to `IN_STOCK` (trial return, loan return, QA pass) it increments.

### 2.5. Money, Scores, and Rounding Discipline

All monetary values in this API are **integer cents** — never floats, never decimal strings. Wherever a computation produces a fractional cent, the result is rounded half-up to the nearest whole cent. Two calculation families round **at each pinned step before moving to the next** rather than rounding once at the end; those steps are called out in their business narratives (the claim provisional total rounds per line and then sums; the trial conversion fee rounds the daily credit, the credit cap, and the service fee each as they are computed). Sum-then-round is explicitly not used for claim estimates, because it can differ from round-then-sum by whole cents.

Clinical and satisfaction scores — `acuity_score`, `contrast_score`, `field_loss_pct`, `task_score`, `satisfaction_score`, and `acuity_delta` — are integers between 0 and 100 inclusive. Composite outcome scores are likewise integers in the 0–100 range produced by rounding half-up.

### 2.6. The Logical Clock and the Daily Sweep

The server maintains a logical clock. At startup its value is exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. A `ClinicAdmin` may set it to a supplied `to_iso8601` instant via the test-driving capability; the response reports the new `current_utc`. Every timestamp the system records — `decided_at`, `dispensed_at`, `loaned_at`, `returned_at`, `past_due_since`, and the like — is taken from this logical clock, and every time-window comparison (trial expiry, loan overdue, subscription periods, funding validity) is evaluated against it. These clock-derived business timestamps — including computed ones such as `trial_ends_at`, `due_at`, and `period_end`, and the `current_utc` reported when the clock is set — are serialized as ISO 8601 UTC in the clock's own form: `YYYY-MM-DDTHH:MM:SSZ`, carrying fractional seconds (three digits) only when the instant actually has sub-second precision. Datetime values supplied by the caller (such as `valid_from`, `valid_until`, `service_date`, `period_start`, `scheduled_start`, `scheduled_end`, and `to_iso8601`) are parsed, normalized to UTC, and re-serialized in this same form when echoed back, rather than echoed verbatim. Only `created_at` and `updated_at` use the three-fractional-digit format pinned in §2.4.

A `ClinicAdmin` may also trigger the **daily sweep**, which applies five transitions in a pinned processing order. Within a single run the sweep processes entity types in exactly this sequence — (1) device orders, (2) loan agreements, (3) subscriptions entering past-due, (4) subscriptions entering suspension, (5) funding authorizations — and within each type it visits matching entities in `created_at` ascending order:

1. A device order whose `fulfillment_type` is `TRIAL`, whose status is `ACTIVE`, and whose `trial_ends_at` is strictly before the current clock transitions `ACTIVE → EXPIRED`.
2. A loan agreement in `ACTIVE` whose `due_at` is strictly before the current clock transitions `ACTIVE → OVERDUE`, with `overdue_days` recomputed as the whole days past `due_at`.
3. A subscription in `ACTIVE` whose `period_end` is strictly before the current clock transitions `ACTIVE → PAST_DUE`, stamping `past_due_since` with the value of `period_end`.
4. A subscription in `PAST_DUE` transitions `PAST_DUE → SUSPENDED` once the current clock is strictly more than 14 days after its `past_due_since`.
5. A funding authorization in `APPROVED` whose `valid_until` is strictly before the current clock transitions `APPROVED → EXPIRED`.

All five boundaries are strict: exact equality of the clock with the threshold does **not** trigger the transition. The sweep response enumerates what moved, as `expired_order_ids`, `overdue_loan_ids`, `past_due_subscription_ids`, `suspended_subscription_ids`, and `expired_authorization_ids`.

### 2.7. Nested Resource Retrieval and Validation Order

Requests targeting nested paths are validated left to right. The first path identifier that does not correspond to an existing resource short-circuits the request with `ERR_NOT_FOUND` (HTTP 404) before any later segment or body reference is examined; foreign keys supplied in a request body are existence-checked under the same rule. More broadly, every request passes through a fixed validation funnel, and the **first** failing check determines the error returned:

1. **Authentication** — headers present and role recognized (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the acting role is listed for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. **Body schema** — required fields present, types correct, enum members valid, numeric ranges honored, and ordering constraints such as `scheduled_start` strictly before `scheduled_end` and `valid_from` on or before `valid_until` (`ERR_VALIDATION`, HTTP 400). For any endpoint that reads a request body, a body containing fields beyond the set that endpoint accepts — including client-supplied system-managed properties such as `id`, `version`, `created_at`, or computed counters — is rejected here with `ERR_VALIDATION`; extra fields are never silently ignored. Endpoints that accept no body simply disregard one.
4. **Existence** — path ids and body foreign keys resolve (`ERR_NOT_FOUND`).
5. **Stale-version (OCC)** — the one optimistic-concurrency check in the system (`ERR_STALE_VERSION`, HTTP 412; see §2.9).
6. **State legality** — the target entity is in a state from which the requested transition exists; terminal states reject everything (`ERR_INVALID_STATE`, or `ERR_PLAN_SUSPENDED` when scheduling onto a suspended or completed plan).
7. **Segregation of duties** — adjudicator differs from submitter (`ERR_SEGREGATION_OF_DUTIES`).
8. **Cross-entity state guards** — referral accepted, evaluation finalized, order active, funding approved, loan returned (`ERR_REFERRAL_NOT_ACCEPTED`, `ERR_EVALUATION_NOT_FINAL`, `ERR_ORDER_NOT_ACTIVE`, `ERR_FUNDING_NOT_APPROVED`, `ERR_LOAN_STILL_ACTIVE`).
9. **Temporal windows and overlaps** — claim service date inside the funding window, trial conversion within the trial window, instructor session overlap, subscription overlap (`ERR_FUNDING_WINDOW_INVALID`, `ERR_TRIAL_EXPIRED`, `ERR_SESSION_OVERLAP`, `ERR_SUBSCRIPTION_OVERLAP`).
10. **Domain constraints** — category match, unit availability, eligible-unit pools, plan session caps, completeness of scores at finalize (`ERR_CATEGORY_MISMATCH`, `ERR_UNIT_NOT_AVAILABLE`, `ERR_NO_ELIGIBLE_UNIT`, `ERR_PLAN_SESSION_CAP`, `ERR_ASSESSMENT_INCOMPLETE`).
11. **Fiscal sufficiency** — claim provisional total against remaining funding (`ERR_INSUFFICIENT_FUNDING`).

This ordering matters in practice: a claim submitted against a non-existent authorization reports 404, not a funding error, and a conversion attempted on an expired trial by the wrong role reports 403, not `ERR_TRIAL_EXPIRED`.

### 2.8. Segregation of Duties

The service separates those who request money from those who release it. Every FundingAuthorization records `submitted_by_user_id` when it is submitted, and every Claim records `submitted_by_user_id` when it is submitted; adjudication of either is performed by a `PayerAdjudicator` whose `X-User-ID` **must differ** from the recorded submitter. An adjudication attempted by the same operator who submitted is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). When adjudication succeeds, the adjudicator's `X-User-ID` is recorded as `adjudicated_by_user_id` on the authorization. Resubmission after an appeal overwrites `submitted_by_user_id` with the resubmitting coordinator's id, which re-arms the segregation check against the new submitter.

### 2.9. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: creating an Evaluation. The request must carry `expected_client_version`, holding the value of the target Client's `version` as the caller last observed it. If the client's current `version` differs from `expected_client_version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). The reason this guard exists is the supersede cascade described in §3.2: creating an evaluation retires every existing draft-or-revised evaluation of the same client and increments the client's `version`, so a writer acting on a stale observation must not supersede on top of changes it never saw. No other endpoint accepts a version field.

## 3. Business Logic & Workflows

### 3.1. Intake: Clients and Referrals

A new patient enters the system when an `IntakeCoordinator` registers a **Client** with a `full_name` and `date_of_birth` (an ISO `YYYY-MM-DD` date). The coordinator may also record a `copay_tier` of `STANDARD` or `LOW_INCOME`; when omitted it defaults to `STANDARD`. The tier has a single, precise consequence described in §3.7: on insurance-funded claims, `LOW_INCOME` halves the client's share of the allowed amount. A freshly registered client has `status` `INTAKE`.

Referrals arrive through the same desk. Creating a **Referral** records the `client_id`, a `source_type` of `PHYSICIAN`, `VR_AGENCY`, `INSURANCE`, or `SELF`, and the free-text `referring_party` naming the physician or agency. A referral is born `RECEIVED` and ends either `ACCEPTED` or `DECLINED`; both are terminal. The intake coordinator's decision call carries a `decision` of `ACCEPT` or `DECLINE`. Either way, `decided_at` is stamped with the current logical clock. Acceptance carries one further effect: if the owning client is still `INTAKE`, the client's `status` flips to `ACTIVE` and the client's `version` increments — the client's activation is a side effect of referral acceptance, never a standalone call. The referrals belonging to a client can be listed via the client's referral collection.

### 3.2. Clinical Evaluation and the Supersede Rule

With an accepted referral in hand, a `VisionSpecialist` opens an **Evaluation** for the client, supplying the `client_id`, the `referral_id`, and — because of the OCC guard in §2.9 — the `expected_client_version`. The referral must already be `ACCEPTED`, or creation fails with `ERR_REFERRAL_NOT_ACCEPTED`; the referral must also belong to the same client named in the payload, a mismatch being a plain `ERR_VALIDATION`. Four clinical fields may be supplied at creation — `acuity_score`, `contrast_score`, `field_loss_pct` (each an integer from 0 to 100) and `recommended_category` (one of `MAGNIFIER`, `CCTV`, `SCREEN_READER`) — and all four are optional at creation. The acting specialist's `X-User-ID` is recorded as `evaluator_user_id`. A new evaluation starts in `DRAFT`.

Creation carries a heavyweight side effect that justifies the concurrency guard: **every other evaluation of the same client in `DRAFT` or `REVISED` status is automatically moved to `SUPERSEDED`**, and the client's `version` increments by 1. Only the newest evaluation of a client is ever live; `SUPERSEDED` is terminal.

An evaluation's own lifecycle is a cycle with a one-way exit. Finalizing — allowed from `DRAFT` or `REVISED` — moves the evaluation to `FINALIZED`, but only when all four clinical fields are non-null; attempting to finalize with any of `acuity_score`, `contrast_score`, `field_loss_pct`, or `recommended_category` still null is rejected with `ERR_ASSESSMENT_INCOMPLETE` (HTTP 422). A `FINALIZED` evaluation can be reopened by the specialist's revise action, moving it `FINALIZED → REVISED` and optionally updating any of the four clinical fields in the same call. Revision is blocked while any device order referencing this evaluation sits in `ACTIVE` or `CONVERTED` status — the request is rejected with `ERR_INVALID_STATE` — because equipment already in the field was dispensed against that recommendation. From `REVISED` the evaluation can be finalized again, and the cycle may repeat until a newer evaluation for the client supersedes it. Evaluations may be listed with optional `client_id`, `referral_id`, and `status` filters.

### 3.3. The Device Catalog and Physical Stock

A `ClinicAdmin` maintains the catalog. Creating a **DeviceModel** records its display `name`, a `category` of `MAGNIFIER`, `CCTV`, or `SCREEN_READER`, and a `list_price_cents` of zero or more. Software-flavored models — typically screen readers — may carry a `subscription_monthly_cents` price of zero or more, defaulting to 0 for pure hardware; only models with a strictly positive monthly price can anchor a subscription (§3.8). A model may name a `successor_model_id` pointing at a newer model as an upgrade path, or leave it null; the models pointing *at* a given model can be enumerated through its predecessors collection. At creation both catalog counters, `in_stock_count` and `total_count`, are 0.

Physical inventory arrives one unit at a time. Receiving a **DeviceUnit** records its `device_model_id`, a manufacturer `serial_no` that is unique across all units in the system, and a `condition` of `NEW`, `REFURB`, or `LOANER`. Every unit is born `IN_STOCK`, and both counters on its model recompute (increment) at receipt. From there the unit moves through a cyclic lifecycle: `IN_STOCK → DEPLOYED` when allocated to a purchase or trial order; `IN_STOCK → ON_LOAN` when allocated to a loaner order or selected as a repair loaner; `DEPLOYED → IN_STOCK` when a trial is returned; `ON_LOAN → IN_STOCK` when a loan is returned; `DEPLOYED → IN_STOCK` detour through `IN_REPAIR` when a repair starts on a deployed unit and later passes QA; `IN_STOCK → IN_REPAIR → IN_STOCK` for bench repairs of stock units; and finally `IN_STOCK → RETIRED`, the only terminal state, performed by a `ClinicAdmin` retiring a unit. Each of these moves recomputes the model counters per §2.4. Units can be listed with `device_model_id`, `status`, and `condition` filters, and each unit's repair history is reachable through its repair-ticket collection.

### 3.4. Device Orders: Placement, Allocation, Trial Conversion, Return

The bridge between evaluation and equipment is the **DeviceOrder**. A `VisionSpecialist` places an order with a `client_id`, an `evaluation_id`, a `device_model_id`, and a `fulfillment_type` of `PURCHASE`, `TRIAL`, or `LOANER`. Two cross-entity guards apply at placement. The referenced evaluation must be `FINALIZED` — otherwise `ERR_EVALUATION_NOT_FINAL` — and the model's `category` must equal the evaluation's `recommended_category`, or the placement is rejected with `ERR_CATEGORY_MISMATCH`. When `fulfillment_type` is `TRIAL`, `trial_days` is required and must be between 1 and 60 inclusive; for the other fulfillment types it is ignored. An optional `warranty_cents` of zero or more (defaulting to 0) attaches an extended-warranty add-on that is charged at conversion or purchase. A new order is `PLACED`, with `device_unit_id`, `dispensed_at`, `trial_ends_at`, and `conversion_total_cents` all null.

Allocation dispenses the order, moving it `PLACED → ACTIVE`, and performs unit selection. The caller may name an explicit `device_unit_id`, which must be a unit of this order's model currently `IN_STOCK` — anything else is `ERR_UNIT_NOT_AVAILABLE`. When `device_unit_id` is omitted the server auto-selects: eligibility requires a unit of the order's model in `IN_STOCK`, with `condition` restricted to `NEW` or `REFURB` for a `PURCHASE` order, while `TRIAL` and `LOANER` orders may draw from `LOANER`, `REFURB`, or `NEW` units. Among eligible units, ranking is by condition tier — for trial and loaner, `LOANER` beats `REFURB` beats `NEW`; for purchase, `NEW` beats `REFURB` — and ties break by `created_at` ascending, never by `id`. An empty pool rejects the allocation with `ERR_NO_ELIGIBLE_UNIT`.

Allocation's side effects fan out by fulfillment type. The selected unit leaves `IN_STOCK`: to `DEPLOYED` for purchase and trial, to `ON_LOAN` for a loaner order, with the model counters recomputed either way. `dispensed_at` is stamped with the current logical clock. For a `TRIAL` order, `trial_ends_at` is computed as `dispensed_at` plus `trial_days`. For a `PURCHASE` order, `conversion_total_cents` is computed immediately at allocation using the conversion-fee rule below with zero days used. For a `LOANER` order, a **LoanAgreement** is created recording the `device_order_id`, the client copied from the order, a `loaned_at` of now, a `due_at` exactly 30 days later, and status `ACTIVE`.

A trial concludes in one of three ways. **Conversion** moves the order `ACTIVE → CONVERTED` and is available only when `fulfillment_type` is `TRIAL` (a purchase or loaner order reports `ERR_INVALID_STATE`) and only while the current logical clock is on or before `trial_ends_at` — exact equality with the trial end is still allowed, while even one instant later is rejected with `ERR_TRIAL_EXPIRED` (HTTP 409). Conversion computes `conversion_total_cents` per the rule below and leaves the unit `DEPLOYED`. **Expiry** is the sweep's doing (§2.6), moving a still-active trial `ACTIVE → EXPIRED`. **Return** moves the order to `RETURNED` from either `ACTIVE` or `EXPIRED`, provided the order is a `TRIAL` or `LOANER` — purchase orders can never be returned (`ERR_INVALID_STATE`). Returning pushes the unit back to `IN_STOCK` from `DEPLOYED` or `ON_LOAN`, recomputes the model counters, and for a loaner order additionally transitions the linked LoanAgreement from `ACTIVE` or `OVERDUE` to `RETURNED` with `returned_at` stamped. `CONVERTED` and `RETURNED` are terminal for an order. Orders can be listed with `client_id`, `evaluation_id`, `device_model_id`, `device_unit_id`, and `status` filters.

**The trial conversion fee.** The fee rule has a pinned evaluation order so that no step depends on a later one. First, `days_used` is the number of whole days from `dispensed_at` to the current clock, clamped to the range from 0 up to `trial_days`. Second, the trial credit is the smaller of two quantities: the model's `list_price_cents` multiplied by 2 percent per day used and rounded half-up to a whole cent, or the model's `list_price_cents` multiplied by 30 percent and rounded half-up — the credit can never exceed that 30-percent cap. Third, the device subtotal is `list_price_cents` minus the trial credit. Fourth, the service fee is 12 percent of the device subtotal — computed on the subtotal, **not** on the final total — rounded half-up to a whole cent. Finally, `conversion_total_cents` is the device subtotal plus the service fee plus the order's `warranty_cents`. For a `PURCHASE` order the identical rule runs at allocation with `days_used` equal to 0, which zeroes the trial credit.

### 3.5. Loan Agreements

A **LoanAgreement** is never created directly; it is minted by one of two triggers: allocating a `LOANER` device order, or starting a repair with a loaner request (§3.9). In the order case the agreement records the `client_id` copied from the order, the `device_unit_id` of the loaned unit, and the `device_order_id`; in the repair case it records the `repair_ticket_id` instead, and `client_id` and `device_order_id` are null because a repair ticket has no client. Either way `loaned_at` is the current logical clock, `due_at` is exactly 30 days after `loaned_at`, and the agreement starts `ACTIVE`.

While an agreement is `ACTIVE`, `overdue_days` is 0 until the clock passes `due_at`; the daily sweep then moves it `ACTIVE → OVERDUE` and keeps `overdue_days` current as the whole days between `due_at` and the clock. Return — performed by a `RepairTechnician` or a `VisionSpecialist` — moves the agreement from `ACTIVE` or `OVERDUE` to `RETURNED`, stamps `returned_at`, finalizes `overdue_days` as the whole days between `due_at` and `returned_at` (0 when not overdue), pushes the loaned unit `ON_LOAN → IN_STOCK`, and recomputes the model counters. `RETURNED` is terminal. Agreements can be listed with `client_id`, `device_unit_id`, `device_order_id`, `repair_ticket_id`, and `status` filters.

### 3.6. Training Plans, Sessions, and the No-Show Cascade

Equipment without training is furniture. A `VisionSpecialist` creates a **TrainingPlan** with a `client_id`, a `device_order_id`, and a `total_sessions` count between 1 and 20 inclusive. The referenced order must be `ACTIVE` or `CONVERTED` — an order in any other state triggers `ERR_ORDER_NOT_ACTIVE` — and the order must belong to the same client, a mismatch being `ERR_VALIDATION`. A new plan is `PLANNED` with `completed_sessions` and `no_show_count` both 0.

Sessions are scheduled onto a plan with an `instructor_user_id` (the opaque staff id of the instructor), a `scheduled_start`, and a `scheduled_end` that must be strictly after the start. Two guards protect scheduling. First, the plan must be `PLANNED` or `ACTIVE`: scheduling against a `SUSPENDED` plan — or a `COMPLETED` one — is rejected with `ERR_PLAN_SUSPENDED` (HTTP 409). Second, the number of non-cancelled sessions already on the plan must be below `total_sessions`; a plan at capacity rejects further scheduling with `ERR_PLAN_SESSION_CAP` (HTTP 422). Additionally, the instructor's calendar is protected by a half-open interval overlap check: the new session conflicts with any existing `SCHEDULED` or `COMPLETED` session of the same instructor whose interval overlaps the new one, but because intervals are half-open — start inclusive, end exclusive — a new session starting exactly when another ends is allowed. A genuine conflict is rejected with `ERR_SESSION_OVERLAP` (HTTP 409). A new session is `SCHEDULED`, its `training_plan_id` taken from the nesting path, and the very first session scheduled onto a plan flips the plan `PLANNED → ACTIVE` automatically.

Resolution is where the plan's counters move. A `VisionSpecialist` resolves a `SCHEDULED` session with an `outcome` of `COMPLETED`, `NO_SHOW`, or `CANCELLED`; all three are terminal for the session. Resolving `COMPLETED` increments the plan's `completed_sessions` by 1, and if that brings the count equal to `total_sessions` the plan transitions `ACTIVE → COMPLETED`. Resolving `NO_SHOW` increments `no_show_count` by 1, and when the count reaches 2 or more the plan transitions `ACTIVE → SUSPENDED`, which cascades: every remaining `SCHEDULED` session of the plan is moved to `CANCELLED` as part of the same suspension. This chain — a no-show resolution, to plan suspension, to session cancellation — is the system's cascade-link-3 pattern: one operator action, three levels of mutation, each touched resource refreshing `updated_at` and `version`. Resolving `CANCELLED` simply ends the session with no counter effects. `COMPLETED` and `SUSPENDED` are terminal for the plan. Plans can be listed with `client_id`, `device_order_id`, and `status` filters, and each plan's sessions through its session collection.

### 3.7. Funding Authorizations, Claims, and the Ledger

The funding spine begins when a `FundingCoordinator` creates a **FundingAuthorization** with a `client_id`, a `payer_type` of `VR` or `INSURANCE`, an external `payer_ref` reference number, an `authorized_amount_cents` strictly greater than 0, and a validity window from `valid_from` through `valid_until`, both inclusive, with `valid_until` on or after `valid_from`. A new authorization is `DRAFT` and its `remaining_amount_cents` equals `authorized_amount_cents`.

The authorization's status graph is a cycle with two terminal exits. The coordinator's submit action moves `DRAFT → SUBMITTED`, recording `submitted_by_user_id`. Adjudication by a `PayerAdjudicator` — carrying a `decision` of `APPROVE` or `DENY` and guarded by the segregation rule of §2.8 — moves it `SUBMITTED → APPROVED` or `SUBMITTED → DENIED`, recording `adjudicated_by_user_id`. A denial is not final: the coordinator's appeal moves `DENIED → APPEALED`, and a fresh submit moves `APPEALED → SUBMITTED`, overwriting `submitted_by_user_id` with the resubmitting coordinator. On the approved side, the sweep moves `APPROVED → EXPIRED` once the clock passes `valid_until`; and the moment a claim adjudication drives `remaining_amount_cents` to exactly 0, the authorization moves `APPROVED → EXHAUSTED` automatically. Exhaustion is reversible: a claim void that raises the remaining balance above 0 moves `EXHAUSTED → APPROVED` without operator action. `EXPIRED` and `EXHAUSTED` are terminal as far as operator transitions go — only the system edges described here leave `EXHAUSTED`. Authorizations can be listed with `client_id` and `status` filters.

**Claims** are the draw-down instrument. A `BillingSpecialist` creates a claim with a `funding_authorization_id`, a `device_order_id`, a `service_date`, and `lines` — an array of 1 to 10 line items, each a `line_type` of `DEVICE`, `WARRANTY`, `TRAINING`, or `SHIPPING` with a `unit_price_cents` of zero or more and a `quantity` between 1 and 10. The referenced order must belong to the authorization's client; a cross-client pairing is `ERR_VALIDATION`. At creation the system computes `provisional_total_cents` as the claim's estimated allowed total: for each line, in array order, multiply the line's `unit_price_cents` by its `quantity` and by a payer factor — 1.00 when the authorization's `payer_type` is `VR`, 0.80 when it is `INSURANCE` — rounding each line's product half-up to a whole cent **before** summing; the provisional total is the sum of those per-line rounded amounts. Sum-then-round is deliberately not used. The estimate uses the payer factor of the linked authorization regardless of the authorization's status at creation time. A new claim is `DRAFT`, with `final_amount_cents`, `payer_pays_cents`, and `client_pays_cents` all null.

Submitting a claim is a reservation event with three preconditions, and the general validation funnel of §2.7 fixes their relative order (funding-not-approved is a cross-entity state guard; the window check is temporal; sufficiency is fiscal). The authorization must be `APPROVED`, else `ERR_FUNDING_NOT_APPROVED`. The `service_date` must lie within the inclusive window from `valid_from` to `valid_until`, else `ERR_FUNDING_WINDOW_INVALID` (HTTP 422). And `provisional_total_cents` must not exceed the authorization's `remaining_amount_cents` — exact equality is allowed — else `ERR_INSUFFICIENT_FUNDING` (HTTP 422). A successful submit moves the claim `DRAFT → SUBMITTED`, records `submitted_by_user_id`, and **subtracts** the provisional total from the authorization's `remaining_amount_cents` as a reservation.

Adjudication, again segregation-guarded, carries a `decision` of `PAY` or `DENY`. `DENY` releases the reservation: `remaining_amount_cents` rises by `provisional_total_cents`, and the claim is terminally `DENIED`. `PAY` requires an `allowed_amount_cents` in the adjudication payload and computes the remittance split. The final variant of the estimate rule is discarded entirely here — the adjudicator's `allowed_amount_cents` becomes `final_amount_cents` verbatim. The payer's responsibility is computed as a waterfall: the available funds are the authorization's current `remaining_amount_cents` **plus** this claim's own `provisional_total_cents` (the reservation is still held at this instant); the base is `allowed_amount_cents` for `VR`, or `allowed_amount_cents` multiplied by the 80-percent coinsurance and rounded half-up for `INSURANCE`; `payer_pays_cents` is the smaller of that base and the available funds; and `client_pays_cents` is `allowed_amount_cents` minus `payer_pays_cents`. One subsidy then applies: when the client's `copay_tier` is `LOW_INCOME` **and** the payer is `INSURANCE`, the client share is halved — `client_pays_cents` becomes its prior value multiplied by one half and rounded half-up — and the payer side absorbs the difference, so `payer_pays_cents` is recomputed as `allowed_amount_cents` minus the reduced client share. The ledger settles as: `remaining_amount_cents` rises by `provisional_total_cents` minus `payer_pays_cents` (release the reservation, deduct the payer share); if that leaves the remaining balance at exactly 0 the authorization flips `APPROVED → EXHAUSTED`.

Voiding is the compensating action, available to a `BillingSpecialist` on a `SUBMITTED` or `PAID` claim. Voiding a `SUBMITTED` claim returns `provisional_total_cents` to the remaining balance; voiding a `PAID` claim returns `payer_pays_cents`. Either way, if the authorization was `EXHAUSTED` and the compensation raises `remaining_amount_cents` above 0, the authorization revives `EXHAUSTED → APPROVED`. `DENIED` and `VOIDED` are terminal for a claim. Claims can be listed with `funding_authorization_id`, `device_order_id`, and `status` filters.

The reconciliation invariant across this whole spine is that an authorization's `remaining_amount_cents` always equals its `authorized_amount_cents` minus the sum of `provisional_total_cents` over its `SUBMITTED` claims, minus the sum of `payer_pays_cents` over its `PAID` claims; claims in `DRAFT`, `DENIED`, or `VOIDED` contribute nothing. The transitions above maintain this invariant incrementally, and the aggregate form is the definition against which any drift is reconciled.

### 3.8. Subscriptions: Loyalty Tiers, Renewal, and Prorated Cancellation

Screen-reader software is billed as a subscription. A `BillingSpecialist` creates a **Subscription** with a `client_id`, a `device_model_id`, a `period_start`, and an optional `auto_renew` flag that defaults to false and is purely informational — the daily sweep does not auto-charge anything. The model must carry a `subscription_monthly_cents` strictly greater than 0, else `ERR_VALIDATION`. One overlap rule applies per client-and-model pair: if the same client already has an `ACTIVE` or `PAST_DUE` subscription on the same model whose period overlaps the new one under a **closed**-interval reading — the new `period_start` falling on or before the existing `period_end` conflicts — creation is rejected with `ERR_SUBSCRIPTION_OVERLAP` (HTTP 409). At creation `period_end` is computed as `period_start` plus 30 days, the creation fee is charged, and the subscription starts `ACTIVE`.

Fees follow the loyalty tier rule. The tier is read from the subscription's `total_paid_cents` **prior to the charge being computed**: at least 100000 cents paid earns a 10-percent discount; at least 50000 cents — and note the boundary is inclusive, so exactly 50000 earns it — earns a 5-percent discount; anything below earns none. The charged `last_fee_cents` is the model's `subscription_monthly_cents` multiplied by one minus the tier rate, rounded half-up to a whole cent. On creation the tier is evaluated against a `total_paid_cents` of 0, so the first period always bills at the full monthly price. After charging, `total_paid_cents` grows by `last_fee_cents`.

Renewal, also by a `BillingSpecialist`, works from either `ACTIVE` or `PAST_DUE`. From `ACTIVE` it charges the loyalty fee against the pre-charge `total_paid_cents`, adds it to `total_paid_cents`, and extends `period_end` by a further 30 days. From `PAST_DUE` it does the same fee computation but resets `period_end` to now plus 30 days and clears `past_due_since` to null, reactivating the subscription to `ACTIVE`. The sweep handles the downward path: `ACTIVE → PAST_DUE` past `period_end` (stamping `past_due_since` with `period_end`), then `PAST_DUE → SUSPENDED` once the clock is more than 14 days past `past_due_since`.

Cancellation is available from `ACTIVE`, `PAST_DUE`, or `SUSPENDED` and always ends `CANCELLED`, which is terminal. The proration credit differs by starting state. From `ACTIVE`, `credit_cents` is computed from the days remaining in the period: the whole days from now to `period_end`, clamped to the range 0 to 30, divided by 30 and multiplied by the model's `subscription_monthly_cents`, rounded half-up to a whole cent. From `PAST_DUE` or `SUSPENDED`, `credit_cents` is 0 — there is no proration credit once a subscription has fallen past due. `credit_cents` remains null until cancellation. Subscriptions can be listed with `client_id`, `device_model_id`, and `status` filters.

### 3.9. Repair Tickets, Rework, and the Repair-Loaner Cascade

When a unit misbehaves, a `RepairTechnician` opens a **RepairTicket** with the `device_unit_id` and a free-text `issue_description`. The unit must be `DEPLOYED` or `IN_STOCK` at intake — a unit already `ON_LOAN`, `IN_REPAIR`, or `RETIRED` cannot start a new ticket. The technician's `X-User-ID` is recorded as `technician_user_id`, and the ticket starts `INTAKE` with `rework_count` 0 and `loan_agreement_id` null.

The bench workflow advances through named actions supplied in the `action` field of the advance call. `DIAGNOSE` moves `INTAKE → DIAGNOSED`. `START_REPAIR` moves `DIAGNOSED → IN_REPAIR` and is the heavy transition: the ticket's own unit moves to `IN_REPAIR` from either `DEPLOYED` or `IN_STOCK` (model counters recomputing when it left stock). When the advance carries `needs_loaner` set to true, a three-link cascade executes as one atomic operation. Link 1 creates a **LoanAgreement** for the repair: `repair_ticket_id` set, `loaned_at` now, `due_at` exactly 30 days out, status `ACTIVE`, and the ticket's `loan_agreement_id` filled in. Link 2 selects the loaner unit: eligibility requires an `IN_STOCK` unit in `LOANER` condition of the **same model** as the broken unit, ranked by `created_at` ascending (never by `id`); if the pool is empty the **entire advance is rejected** with `ERR_NO_ELIGIBLE_UNIT` — no ticket state change, no loan created. Link 3 moves the chosen loaner `IN_STOCK → ON_LOAN` and recomputes the model's `in_stock_count`. After repair, `SUBMIT_QA` moves `IN_REPAIR → QA_CHECK`. From `QA_CHECK`, `QA_FAIL` loops back `QA_CHECK → IN_REPAIR` and increments `rework_count` by 1 each time, while `QA_PASS` moves `QA_CHECK → RESOLVED` — but only when the linked loan agreement, if one exists, has already reached `RETURNED`; passing QA with a loan still `ACTIVE` or `OVERDUE` is rejected with `ERR_LOAN_STILL_ACTIVE` (HTTP 409). A successful QA pass returns the repaired unit `IN_REPAIR → IN_STOCK` and recomputes the model counters. `RESOLVED` is terminal. A loan's linked tickets are listable through the loan's repair-ticket collection, and a unit's history through the unit's collection.

### 3.10. Outcome Assessment and Dual-Composite Scoring

The service closes the loop with a measurable outcome. A `VisionSpecialist` creates an **OutcomeAssessment** with a `client_id`, a `kind` of `BASELINE` or `FOLLOW_UP`, a `task_score` and `satisfaction_score` (each an integer 0–100 capturing the client's self-reported task performance and satisfaction), and optionally an `acuity_delta` (integer 0–100, the clinician-measured acuity improvement). At creation the **provisional** composite is computed and stored in `provisional_composite`: one half of `task_score` plus one half of `satisfaction_score`, rounded half-up to an integer. The provisional variant deliberately ignores `acuity_delta` — it reflects self-report only.

Finalizing the assessment — the specialist's finalize call, which may carry `acuity_delta` in the payload — moves it `DRAFT → SCORED` and requires `acuity_delta` to be non-null, whether supplied at creation or at finalize; otherwise the call is rejected with `ERR_ASSESSMENT_INCOMPLETE` (HTTP 422). On finalize the clinician variant computes `final_composite` as three tenths of `acuity_delta` plus four tenths of `task_score` plus three tenths of `satisfaction_score`, rounded half-up to an integer, and stores it. Because the weightings differ, identical inputs generally yield a different final composite than the provisional one — that difference is the intended signal between self-report and clinician judgment. `SCORED` is terminal. A client's assessments are listed through the client's outcome-assessment collection.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — transitions, decisions, adjudications, renewals — return `200 OK`. All endpoints are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/clients` | Create a client (status `INTAKE`) | IntakeCoordinator |
| GET | `/api/clients/{id}` | Get one client | Any authenticated role |
| GET | `/api/clients/{id}/referrals` | List referrals of a client | Any authenticated role |
| GET | `/api/clients/{id}/outcome-assessments` | List outcome assessments of a client | Any authenticated role |
| POST | `/api/referrals` | Create a referral (status `RECEIVED`) | IntakeCoordinator |
| POST | `/api/referrals/{id}/decide` | Accept or decline a referral | IntakeCoordinator |
| POST | `/api/evaluations` | Create an evaluation (OCC-guarded; supersedes the client's prior drafts) | VisionSpecialist |
| GET | `/api/evaluations/{id}` | Get one evaluation | Any authenticated role |
| GET | `/api/evaluations` | List evaluations, filterable | Any authenticated role |
| POST | `/api/evaluations/{id}/finalize` | Finalize an evaluation (`DRAFT`/`REVISED` → `FINALIZED`) | VisionSpecialist |
| POST | `/api/evaluations/{id}/revise` | Reopen a finalized evaluation for revision | VisionSpecialist |
| POST | `/api/device-models` | Create a catalog device model | ClinicAdmin |
| GET | `/api/device-models/{id}` | Get one device model | Any authenticated role |
| GET | `/api/device-models/{id}/predecessors` | List models whose successor points at this model | Any authenticated role |
| POST | `/api/device-units` | Receive a physical unit into stock | ClinicAdmin |
| GET | `/api/device-units/{id}` | Get one device unit | Any authenticated role |
| GET | `/api/device-units` | List units, filterable | Any authenticated role |
| GET | `/api/device-units/{id}/repair-tickets` | List repair tickets of a unit | Any authenticated role |
| POST | `/api/device-units/{id}/retire` | Retire an `IN_STOCK` unit | ClinicAdmin |
| POST | `/api/device-orders` | Place a device order (`PLACED`) | VisionSpecialist |
| GET | `/api/device-orders/{id}` | Get one device order | Any authenticated role |
| GET | `/api/device-orders` | List orders, filterable | Any authenticated role |
| POST | `/api/device-orders/{id}/allocate` | Allocate a unit and dispense (`PLACED` → `ACTIVE`) | VisionSpecialist |
| POST | `/api/device-orders/{id}/convert` | Convert a trial to purchase within the trial window | VisionSpecialist |
| POST | `/api/device-orders/{id}/return` | Return a `TRIAL`/`LOANER` order | VisionSpecialist |
| GET | `/api/loan-agreements/{id}` | Get one loan agreement | Any authenticated role |
| GET | `/api/loan-agreements` | List loans, filterable | Any authenticated role |
| POST | `/api/loan-agreements/{id}/return` | Return a loaned unit (`ACTIVE`/`OVERDUE` → `RETURNED`) | RepairTechnician, VisionSpecialist |
| POST | `/api/training-plans` | Create a training plan (`PLANNED`) | VisionSpecialist |
| GET | `/api/training-plans/{id}` | Get one training plan | Any authenticated role |
| GET | `/api/training-plans` | List plans, filterable | Any authenticated role |
| POST | `/api/training-plans/{id}/sessions` | Schedule a session on a plan | VisionSpecialist |
| GET | `/api/training-plans/{id}/sessions` | List sessions of a plan | Any authenticated role |
| POST | `/api/training-sessions/{id}/resolve` | Resolve a scheduled session (`COMPLETED`/`NO_SHOW`/`CANCELLED`) | VisionSpecialist |
| POST | `/api/funding-authorizations` | Create a funding authorization (`DRAFT`) | FundingCoordinator |
| GET | `/api/funding-authorizations/{id}` | Get one funding authorization | Any authenticated role |
| GET | `/api/funding-authorizations` | List authorizations, filterable | Any authenticated role |
| POST | `/api/funding-authorizations/{id}/submit` | Submit for payer adjudication | FundingCoordinator |
| POST | `/api/funding-authorizations/{id}/adjudicate` | Payer decision on an authorization (segregation enforced) | PayerAdjudicator |
| POST | `/api/funding-authorizations/{id}/appeal` | Appeal a denial | FundingCoordinator |
| POST | `/api/claims` | Create a claim with line items (`DRAFT`) | BillingSpecialist |
| GET | `/api/claims/{id}` | Get one claim | Any authenticated role |
| GET | `/api/claims` | List claims, filterable | Any authenticated role |
| POST | `/api/claims/{id}/submit` | Submit a claim; reserves the provisional amount | BillingSpecialist |
| POST | `/api/claims/{id}/adjudicate` | Payer decision on a claim (segregation enforced) | PayerAdjudicator |
| POST | `/api/claims/{id}/void` | Void a `SUBMITTED` or `PAID` claim (compensating) | BillingSpecialist |
| POST | `/api/repair-tickets` | Open a repair ticket (`INTAKE`) | RepairTechnician |
| GET | `/api/repair-tickets/{id}` | Get one repair ticket | Any authenticated role |
| GET | `/api/loan-agreements/{id}/repair-tickets` | List repair tickets linked to a loan | Any authenticated role |
| POST | `/api/repair-tickets/{id}/advance` | Advance the repair workflow (`DIAGNOSE`/`START_REPAIR`/`SUBMIT_QA`/`QA_PASS`/`QA_FAIL`) | RepairTechnician |
| POST | `/api/subscriptions` | Create a subscription (`ACTIVE`) | BillingSpecialist |
| GET | `/api/subscriptions/{id}` | Get one subscription | Any authenticated role |
| GET | `/api/subscriptions` | List subscriptions, filterable | Any authenticated role |
| POST | `/api/subscriptions/{id}/renew` | Renew (extends or reactivates; loyalty tier applied) | BillingSpecialist |
| POST | `/api/subscriptions/{id}/cancel` | Cancel (prorated credit only from `ACTIVE`) | BillingSpecialist |
| POST | `/api/outcome-assessments` | Create an outcome assessment (`DRAFT`; provisional composite) | VisionSpecialist |
| GET | `/api/outcome-assessments/{id}` | Get one outcome assessment | Any authenticated role |
| POST | `/api/outcome-assessments/{id}/finalize` | Finalize (`DRAFT` → `SCORED`; clinician composite) | VisionSpecialist |
| POST | `/api/ops/run_daily` | Run the daily sweep against the logical clock | ClinicAdmin |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (test-driving) | ClinicAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_SUSPENDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_REFERRAL_NOT_ACCEPTED` | 409 |
| `ERR_EVALUATION_NOT_FINAL` | 409 |
| `ERR_ORDER_NOT_ACTIVE` | 409 |
| `ERR_FUNDING_NOT_APPROVED` | 409 |
| `ERR_LOAN_STILL_ACTIVE` | 409 |
| `ERR_FUNDING_WINDOW_INVALID` | 422 |
| `ERR_TRIAL_EXPIRED` | 409 |
| `ERR_SESSION_OVERLAP` | 409 |
| `ERR_SUBSCRIPTION_OVERLAP` | 409 |
| `ERR_CATEGORY_MISMATCH` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_NO_ELIGIBLE_UNIT` | 409 |
| `ERR_PLAN_SESSION_CAP` | 422 |
| `ERR_ASSESSMENT_INCOMPLETE` | 422 |
| `ERR_INSUFFICIENT_FUNDING` | 422 |
