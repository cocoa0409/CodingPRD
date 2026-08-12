# Contingent Labor Rate Card & SOW Management API — Product Requirements Document

## 1. Introduction

Contingent workforce programs live or die on rate discipline. A program office that cannot prove, line by line, that every bill rate sits inside a negotiated rate card — and that every markup stays within the cap agreed for that supplier's tier — will fail its next audit and overpay for labor in the meantime. At the same time, the legal boundary between staff augmentation (a requisition billed by the hour against timesheets) and a statement of work (a milestone-billed deliverable the supplier self-manages) is a genuine misclassification risk: classify an engagement wrong and the organization inherits co-employment exposure. This document specifies an API that gives the program office a single system of record for both commercial models — rate cards with explicit effective windows, supplier tiering driven by measured performance, distribution rules that fan work out to a ranked shortlist, timesheet and milestone acceptance with full spend ledgering, invoice consolidation, tenure limits with conversion-to-employee fees, and a compliance audit engine that re-checks booked rates against the card that governs today.

The API is built for a segregation-of-duties operating model. Client-side hiring managers own engagements and approve work; supplier coordinators respond to offers and deliver milestones; contingent workers submit only their own timesheets; finance analysts finalize and pay invoices under a two-person rule; and the program administrator governs everything else — cards, suppliers, classification decisions, distribution, bookings, conversions, and audits. Every consequential money movement flows through an append-only spend ledger so that spend visibility is a read, not a reconciliation exercise. All monetary values are integer cents, all calendar dates are ISO `YYYY-MM-DD` strings, and all timestamps are ISO 8601 UTC, so that two independent implementations of this contract agree to the cent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, carrying a role that is not one of the declared roles below, or carrying the role `Anonymous` is unauthenticated and is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint — or whose entity-backed identity does not match the resource being acted on — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as the `X-User-Role` header must carry them, are:

- `ProgramAdmin` — the contingent workforce program office administrator. This role owns rate card authoring, activation, retirement and revision; supplier onboarding, suspension, reinstatement and tier evaluation; classification decisions on engagements; distribution and offer withdrawal; the offer expiry sweep; assignment booking, activation, extension, termination and completion; conversion approval, decline and completion; compliance audit runs and audit disposition; worker offboard-completion and rehire; and the logical clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `HiringManager` — the client-side manager who owns engagements. This role creates engagements, submits them for classification review, amends and closes them; creates, accepts and rejects milestones; approves and rejects timesheets; and requests worker conversions. When `X-User-Role` is `HiringManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow captures an actor (for example, as `approved_by_user_id` on a timesheet or `accepted_by_user_id` on a milestone) but does not compare it to any entity's `id`.
- `SupplierCoordinator` — a staffing supplier account. This role responds to distribution offers, delivers milestones, and registers workers — in each case only for its own supplier. When `X-User-Role` is `SupplierCoordinator`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` compare the resource's supplier foreign-key field to `X-User-ID`.
- `Worker` — a contingent worker, who creates and submits timesheets only against that worker's own assignments. When `X-User-Role` is `Worker`, `X-User-ID` is the `id` of the acting `Worker`; ownership checks on any resource that references a `Worker` compare the resource's worker foreign-key field to `X-User-ID`.
- `FinanceAnalyst` — finance operations. This role creates, finalizes, marks paid and voids invoices, and voids approved timesheets. When `X-User-Role` is `FinanceAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow captures an actor (for example, as `finalized_by_user_id` or `paid_by_user_id` on an invoice) but does not compare it to any entity's `id`.
- `Anonymous` — the unauthenticated caller. Every request presented as `Anonymous` maps to `ERR_UNAUTHENTICATED`.

Read endpoints are broadly shared: rate cards, suppliers, engagements, workers, assignments, timesheets and milestones are readable by all five authenticated roles. Distribution offers and invoices are readable by `ProgramAdmin`, `HiringManager`, `SupplierCoordinator` and `FinanceAnalyst` but not by `Worker`. Conversion requests and compliance audits are readable by `ProgramAdmin`, `HiringManager` and `FinanceAnalyst`. The spend ledger and the consolidated spend summary are readable only by `ProgramAdmin` and `FinanceAnalyst`.

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

List endpoints accept two query parameters. `limit` controls page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many records are skipped and defaults to 0. Every list response carries `limit`, `offset`, `total_count` and `has_more` in its `meta` object, so a client can page deterministically to the end of a collection. Unless an endpoint states otherwise, list results are sorted by `created_at` ascending — the oldest record first.

### 2.4. The Logical Clock

All time-dependent behavior in this system evaluates against a server-held logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it continues to read that default. A `ProgramAdmin` may move the clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`. Every server-stamped timestamp — `created_at`, `updated_at`, an offer's `offered_at` and `responded_at`, and every other stamped field — reads this logical clock, which means entities created while the clock is frozen share identical `created_at` values. Tenure accumulation, rate card effective windows, offer expiry, and every other time-dependent rule described in §3 evaluate against this clock and no other source of time.

### 2.5. Resource Identity and Common Properties

Every resource is identified by an `id` that is a server-minted UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version`, an integer that starts low and increments by one on every mutation of that resource. Two resource kinds are deliberately lighter: an invoice line and a spend ledger entry carry only `id` and `created_at`. Both `updated_at` and `version` are absent on those two kinds — they are immutable records of an event, never edited in place.

Where an endpoint address nests one resource beneath another (milestones beneath their engagement), path identifiers are resolved left to right: the parent identifier is resolved first, then the nested identifier within it. Any identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404).

### 2.6. Money, Hours, and Rounding Conventions

All money in this API is expressed as integer cents — there are no fractional-cent values anywhere, and no decimal money. Calendar dates are ISO `YYYY-MM-DD` strings; datetimes are ISO 8601 UTC. Hours on timesheets are decimal numbers carried to at most two decimal places. Wherever a calculation in this document produces a non-integer cent or day value and a rounding step is specified, the rounding method is round half up — a fraction of exactly one half rounds away from zero — and the result is rounded to whole cents (or whole days, where stated). Calculations that are specified as pure integer comparisons involve no rounding at all, and the prose in §3 states explicitly which regime each calculation uses.

### 2.7. Validation Order and Error Precedence

A single request can violate several rules at once. When it does, the error that surfaces is determined by a fixed precedence order, evaluated from first to last:

1. **Authentication** — missing or invalid `X-User-ID` / `X-User-Role` headers, an undeclared role, or `Anonymous`: `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Authorization** — the role is not listed for the endpoint, or an entity-backed identity mismatches the resource owner (a `SupplierCoordinator` acting on another supplier's offers, milestones or workers; a `Worker` acting on another worker's timesheets): `ERR_FORBIDDEN` (403). Applies to every endpoint.
3. **Request shape** — required fields present, types valid, enum values within their declared sets, dates in `YYYY-MM-DD` form, hour values carried to at most two decimal places. Violations yield `ERR_VALIDATION` (400) on all creation and action endpoints. Computed or system-owned fields supplied in a request body are ignored silently — they are not an error.
4. **Existence** — path identifiers resolve left to right; a missing resource yields `ERR_NOT_FOUND` (404).
5. **State validity** — the target resource must be in a valid from-state for the requested transition. A generic wrong-from-state rejection is `ERR_INVALID_STATE` (409); two transitions carry dedicated codes evaluated at this same tier — milestone delivery against an engagement that is not `ACTIVE` yields `ERR_ENGAGEMENT_NOT_ACTIVE` (409), and timesheet creation or submission against an assignment that is not `ACTIVE` yields `ERR_ASSIGNMENT_NOT_ACTIVE` (409).
6. **Business safety** — suspension, tenure-limit, misclassification and segregation-of-duties guards: `ERR_SUPPLIER_SUSPENDED` (422), `ERR_TENURE_LIMIT_EXCEEDED` (422), `ERR_MISCLASSIFICATION_RISK` (422), and `ERR_SOD_VIOLATION` (403). These outrank the referential and fiscal failures below — a suspended supplier, for instance, surfaces `ERR_SUPPLIER_SUSPENDED` even when the same request would also have failed a referential check.
7. **Business constraints** — rate card window overlap, worker double-booking, duplicate timesheet periods, duplicate conversion requests, duplicate open invoices, hour ceilings, and empty distribution pools (`ERR_RATE_CARD_WINDOW_OVERLAP`, `ERR_WORKER_DOUBLE_BOOKED`, `ERR_DUPLICATE_TIMESHEET_PERIOD`, `ERR_CONVERSION_ALREADY_REQUESTED`, `ERR_INVOICE_ALREADY_OPEN`, all 409; `ERR_HOURS_EXCEED_MAX`, `ERR_NO_ELIGIBLE_SUPPLIER`, both 422).
8. **Temporal containment** — timesheet periods must sit inside their assignment's date span (`ERR_PERIOD_OUTSIDE_ASSIGNMENT`, 422), and the governing rate card's window must contain an assignment's start date (`ERR_CARD_NOT_EFFECTIVE`, 422).
9. **Referential integrity** — cards active and key-matched (`ERR_RATE_CARD_INACTIVE`, 422), engagement-type gating (`ERR_ENGAGEMENT_TYPE_MISMATCH`, 422), offer acceptance and engagement matching (`ERR_OFFER_NOT_ACCEPTED`, 422), and worker-supplier matching (`ERR_WORKER_SUPPLIER_MISMATCH`, 422).
10. **Fiscal limits** — rate ceilings, markup caps, pay floors, budget limits and empty invoices (`ERR_RATE_ABOVE_CEILING`, `ERR_MARKUP_ABOVE_CAP`, `ERR_PAY_BELOW_FLOOR`, `ERR_BUDGET_EXCEEDED`, `ERR_INVOICE_EMPTY`, all 422).

The relative order matters most inside compound operations. Booking an assignment, for example, evaluates suspension and tenure before double-booking, double-booking before card-window containment, card-window containment before referential key matching, and all of those before the three fiscal checks — and within the fiscal tier the bill-rate ceiling is checked first, then markup, then the pay floor.

### 2.8. Optimistic Concurrency Control

Two write operations in this API are optimistic-concurrency guarded; no other endpoint takes a version field.

Amending an engagement requires the request to carry `expected_engagement_version`, holding the engagement `version` the client last observed. If the engagement's current `version` has advanced beyond that value — because another writer amended the engagement in the meantime — the amendment is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), preventing the client from overwriting an engagement state it never observed.

Creating a revision of a rate card works the same way: the request must carry `expected_rate_card_version` matching the source card's current `version`. A mismatch is rejected with `ERR_STALE_RATE_CARD_VERSION` (HTTP 412). Both version fields are non-optional on their respective endpoints.

### 2.9. Rate Card Effective Windows and Governing-Card Resolution

A rate card prices one key — the triple of `role_code`, `skill_code` and `geo_code` — over a half-open effective window that runs from `effective_from` up to but not including `effective_to`. Half-open semantics are load-bearing throughout: a card governs its start date and stops governing the instant its end date arrives. Two cards with the same key may touch — one card's `effective_from` equal to another's `effective_to` — without conflicting; adjacency with a gap of zero days is explicitly allowed. What is forbidden is two `ACTIVE` cards with the same key whose half-open windows share even a single day.

Whenever the system needs "the governing rate card" — at timesheet approval, at compliance audit time, anywhere a rate must be checked against the card in force — it resolves the `ACTIVE` card matching the engagement's key whose half-open window contains the logical clock date at the moment of evaluation. Because assignments are booked against a specific card but audits run later, an audit can legitimately evaluate a booking against a different card than the one it was booked under, when a revision has since taken effect.

### 2.10. Supplier Performance Counters

Each supplier carries a set of system-maintained counters that feed tiering, distribution and audit: `offers_made_count` (every distribution offer ever created for the supplier), `offers_filled_count` (offers that reached `CONSUMED` — an assignment was booked against them), `open_offers_count` (offers currently `OFFERED`, i.e. outstanding distribution slots), `completed_assignments_count`, `open_violation_count` (compliance audits in `OPEN` or `ACKNOWLEDGED` linked to the supplier), `milestones_delivered_count` (incremented on each delivery transition, including redeliveries), and `milestones_accepted_count`. Each counter starts at zero and moves only through the workflows described in §3 — there is no endpoint that writes a counter directly. A supplier's `tier_score` is null until the first scored tier evaluation produces one, and `spend_ytd_cents` is a derived figure maintained from the spend ledger (§2.11).

### 2.11. The Spend Ledger

Approved spend is recorded in an append-only ledger. Each `SpendLedgerEntry` references the supplier and engagement it belongs to, plus the subject that caused it — a `timesheet_id` for timesheet events, a `milestone_id` for milestone acceptance, and an `invoice_id` reserved for invoice-level entries. Its `entry_type` is one of `TIMESHEET_APPROVED`, `TIMESHEET_VOIDED` or `MILESTONE_ACCEPTED`; its `delta_cents` is the signed amount applied to the supplier's spend — positive on approval or acceptance, negative on a void — and its `running_balance_cents` records the supplier's spend balance immediately after the entry, with entries ordered chronologically by `created_at`. A supplier's `spend_ytd_cents` is exactly the sum of `delta_cents` across its ledger entries — approved spend net of voids — so the ledger is never edited, only appended to, and every reversal is itself a new entry.

## 3. Business Logic & Workflows

### 3.1. Rate Card Authoring, Activation, and Revision

A `ProgramAdmin` authors a rate card by supplying its key — `role_code`, `skill_code` and `geo_code` — together with the `currency` (an ISO 4217 code), the `pay_rate_floor_cents` (the minimum hourly pay rate the card permits), the `bill_rate_ceiling_cents` (the maximum hourly bill rate), the `max_markup_pct` (the largest markup fraction the card allows, expressed as a fraction such as 0.25), and the effective window endpoints `effective_from` and `effective_to`. A new card is born in `DRAFT` status and prices nothing until activated.

Activation moves a card `DRAFT` → `ACTIVE` and enforces the window rule of §2.9: if any other `ACTIVE` card with the identical key has a half-open window overlapping this card's window by even one day, activation is rejected with `ERR_RATE_CARD_WINDOW_OVERLAP` (409). Windows that merely touch at a single endpoint do not overlap and both cards may be active. Activation attempted on a card that is not in `DRAFT` is a wrong-from-state rejection. Retirement moves a card `ACTIVE` → `RETIRED`; `RETIRED` is terminal, and a retired card never governs anything again.

Cards evolve by revision rather than editing in place. Creating a revision of a source card — allowed while the source is `ACTIVE` or `DRAFT` — produces a brand-new card in `DRAFT` whose fields are copied from the source, with any of `pay_rate_floor_cents`, `bill_rate_ceiling_cents`, `max_markup_pct`, `effective_from` and `effective_to` overridden by values supplied in the request. The new card's `supersedes_id` points back at the source card's `id` (it is null on original cards), and the act of revising increments the source card's `version` by one — which is exactly why the revision request is concurrency-guarded by `expected_rate_card_version` as specified in §2.8. A client holding a stale view of the card learns of it through `ERR_STALE_RATE_CARD_VERSION`, not through a silent overwrite. The rate card collection can be listed with filters on `role_code`, `skill_code`, `geo_code`, `status` and `supersedes_id`.

### 3.2. Supplier Onboarding, Tiering, and Governance

Suppliers enter the program through a `ProgramAdmin` onboarding call carrying the legal `name`, a `supplier_code` (a short code unique across suppliers, used as the deterministic final tie-break in distribution ranking), and an initial `tier` of `PREFERRED`, `APPROVED` or `PROBATION`. A supplier's lifecycle `status` starts at `ACTIVE`; all of its performance counters (§2.10) start at zero and its `tier_score` starts null.

Tier is subsequently earned, not assigned. A `ProgramAdmin` may run a per-supplier tier evaluation checkpoint that recomputes `tier_score` from the supplier's own counters. The scoring rule has an explicit insufficient-data branch: a supplier with fewer than 3 completed assignments is not scored at all — `tier_score` stays null and the existing `tier` is left unchanged. Otherwise three components are computed: the fill component is `offers_filled_count` divided by `offers_made_count`, capped at 1.0, with the denominator treated as at least 1; the compliance component is 1 minus `open_violation_count` divided by `completed_assignments_count`, floored at 0.0, with the denominator again treated as at least 1; and the acceptance component is `milestones_accepted_count` divided by `milestones_delivered_count`, capped at 1.0 with the denominator treated as at least 1 — which pins the empty-pool case: a supplier that has delivered no milestones scores exactly 0 on the acceptance component, it does not skip the component. The score is 100 times the weighted blend — 0.4 times the fill component plus 0.4 times the compliance component plus 0.2 times the acceptance component — rounded half up to a whole integer. The tier band boundaries are inclusive at the bottom: a score of 85 or better earns `PREFERRED`, 70 through 84 earns `APPROVED`, and below 70 drops to `PROBATION` — so exactly 85 is `PREFERRED` and exactly 70 is `APPROVED`.

Governance actions are suspension and reinstatement. Suspending moves a supplier `ACTIVE` → `SUSPENDED` and cascades downward: every distribution offer of that supplier currently `OFFERED` becomes `WITHDRAWN`, and the supplier's `open_offers_count` is decremented once per withdrawn offer. Reinstatement moves `SUSPENDED` → `ACTIVE` with no side effects. While a supplier is `SUSPENDED`, three operations are refused with `ERR_SUPPLIER_SUSPENDED` (422): accepting an offer through the supplier response flow, booking an assignment that would engage the supplier, and delivering a milestone. Consistent with §2.7, this refusal outranks referential and fiscal failures on the same request.

### 3.3. Engagement Classification, Amendment, and Closure

A `HiringManager` drafts an engagement with a `title`, an `engagement_type` of `REQUISITION` (staff augmentation, billed against timesheets) or `SOW` (milestone-billed) — a field that is immutable after creation — the `role_code`, `skill_code` and `geo_code` used to resolve the governing rate card, a `payment_basis` of `HOURLY` or `FIXED`, a `supervision_level` of `DAILY` (the client supervises daily work) or `MILESTONE` (the supplier self-manages to deliverables), an expected `duration_months`, a total authorized `budget_cents`, and an optional `prorata_conversion` flag (default false) that later influences conversion fee variant selection. A new engagement is in `DRAFT`, with `misclassification_risk` null, `committed_spend_cents` at zero, `awarded_supplier_id` null, and `budget_audit_raised` false.

Submitting for review moves the engagement `DRAFT` → `IN_REVIEW` and computes its misclassification risk from its own declared fields. The risk is `HIGH` in exactly two shapes: an `SOW` engagement whose `payment_basis` is `HOURLY` or whose `supervision_level` is `DAILY` (a statement of work that walks like staff augmentation), or a `REQUISITION` whose `payment_basis` is `FIXED` (staff augmentation priced like a deliverable). Every other combination is `LOW`. The computed value is stored on `misclassification_risk`.

Classification decisions belong to the `ProgramAdmin` and are submitted through a `decision` field on the request. A `decision` of `REWORK` sends the engagement `IN_REVIEW` → `DRAFT` and records the request's `note` into `classification_note`; the loop `DRAFT` → `IN_REVIEW` → `DRAFT` is legal and repeatable. A `decision` of `APPROVE` moves the engagement `IN_REVIEW` → `OPEN`, but only when the risk is `LOW` or the request supplies a `risk_override_rationale`: approving a `HIGH`-risk engagement without that rationale is rejected with `ERR_MISCLASSIFICATION_RISK` (422), and when the override is used the rationale text becomes the `classification_note`.

While an engagement is non-terminal, its owner may amend `budget_cents`, `duration_months` or `title` through the concurrency-guarded amendment operation of §2.8, which requires `expected_engagement_version` and increments the engagement's `version` by one on success. Engagements are listed with filters on `status`, `engagement_type` and `awarded_supplier_id`.

Closure is available from `OPEN`, `FILLING` and `ACTIVE`, and always terminates the engagement in `CLOSED`. From `OPEN` there is nothing booked yet: all `OFFERED` and `ACCEPTED` offers of the engagement become `WITHDRAWN`, and each affected supplier's `open_offers_count` is decremented once per `OFFERED` offer withdrawn. From `FILLING` the same offer withdrawal happens, and in addition every `PENDING` assignment of the engagement becomes `TERMINATED` with `termination_reason` set to `ENGAGEMENT_CLOSED`; each worker left with no remaining `PENDING` or `ACTIVE` assignment moves to `OFFBOARDING`. From `ACTIVE` the cascade is the full chain: every `PENDING` or `ACTIVE` assignment becomes `TERMINATED` with `termination_reason` `ENGAGEMENT_CLOSED` and `actual_end_date` set to the logical clock date; for each terminated assignment, if its worker has no remaining assignment in `PENDING` or `ACTIVE`, the worker moves to `OFFBOARDING`; and all `OFFERED` and `ACCEPTED` offers are withdrawn with the same per-offer counter adjustment.

### 3.4. Supplier Distribution and Offer Handling

Distributing an `OPEN` engagement runs the supplier selection rule and moves the engagement `OPEN` → `FILLING`. Eligibility is strict: a candidate supplier must be `ACTIVE`, must hold tier `PREFERRED` or `APPROVED`, and must have headroom under its parallel-offer cap — fewer than 5 currently open offers for a `PREFERRED` supplier, fewer than 3 for an `APPROVED` one. The eligible pool is ranked by a deterministic total order: first by tier, `PREFERRED` before `APPROVED`; then by `tier_score` descending, with a null score treated as exactly 70; then by `created_at` ascending; and finally by `supplier_code` ascending as the deterministic tie-break. No supplier `id` ever participates in ranking. The top 3 suppliers of the ranked pool each receive a `DistributionOffer`; if the eligible pool is empty the distribution is rejected with `ERR_NO_ELIGIBLE_SUPPLIER` (422) and no offer is created.

Each created offer starts `OFFERED`, stamped with `offered_at` from the logical clock and a `response_due_at` exactly 7 days later. Every selected supplier's `offers_made_count` and `open_offers_count` each increase by one. The distribution response returns the created offers ordered by selection rank, best first.

The supplier's response comes through a single respond action carrying an `action` of `ACCEPT` or `DECLINE`, and it is ownership-checked: the caller's `X-User-ID` must equal the offer's `supplier_id`. Either response requires the offer to still be `OFFERED`, decrements the supplier's `open_offers_count` by one, and stamps `responded_at` from the logical clock. Accepting additionally requires the supplier to be `ACTIVE` — a suspended supplier's acceptance is refused with `ERR_SUPPLIER_SUSPENDED` — and triggers a bubble-up: if the engagement is still `FILLING`, the first acceptance moves it to `ACTIVE` and sets `awarded_supplier_id` to the accepting supplier, but only while that field is still null. Declining simply closes the offer as `DECLINED`. A `ProgramAdmin` may also withdraw an `OFFERED` offer outright, moving it to `WITHDRAWN` with the same counter decrement.

Offers that outlive their window are reaped by an ops-run expiry sweep: a checkpoint operation over all offers that moves every `OFFERED` offer whose `response_due_at` is earlier than the logical clock to `EXPIRED`, decrementing the owning supplier's `open_offers_count` once per expired offer and returning an `expired_count`. Offers can be listed with filters on `engagement_id`, `supplier_id` and `status`; the collection is reverse-reachable from both sides and is not exposed to the `Worker` role.

### 3.5. Worker Registration, Assignment Booking, and Tenure

Workers are registered by a `SupplierCoordinator` or a `ProgramAdmin` with the employing `supplier_id`, the worker's `full_name`, an `email` unique across workers, and an optional `tenure_carryover_days` crediting prior service toward the tenure limit (default 0). A `SupplierCoordinator` may register only under its own supplier id — the request's `supplier_id` must equal `X-User-ID`. A worker is born `ONBOARDING` with `conversion_status` `NONE`, and exposes a computed `cumulative_tenure_days` on read.

Tenure is accumulated in whole days over closed, both-endpoints-inclusive date spans. For a given assignment, the span through a date runs from `start_date` through the earlier of the assignment's effective end and that date, counting both endpoints — so the day count is the number of calendar days from `start_date` through that earlier date, inclusive. The effective end is `actual_end_date` for `COMPLETED` or `TERMINATED` assignments, `end_date` for `PENDING` ones, and the earlier of `end_date` and the logical clock date for `ACTIVE` ones. A worker's cumulative tenure is `tenure_carryover_days` plus the sum, over all of the worker's assignments in `PENDING`, `ACTIVE`, `COMPLETED` or `TERMINATED`, of each span through the logical clock date — any span that would come out negative contributes zero. Because double-booking is prevented (below), these spans never overlap, so plain summation is well-defined.

Booking a worker onto an engagement is the most heavily guarded write in the system. The request names the `worker_id`, the `engagement_id`, the `offer_id` of the accepted distribution offer, the `rate_card_id` pricing the booking, the hourly `bill_rate_cents` charged to the client, the hourly `pay_rate_cents` paid to the worker, and the inclusive `start_date` and `end_date`. The guards fire in the precedence order of §2.7: the supplier copied from the offer must not be `SUSPENDED` (`ERR_SUPPLIER_SUSPENDED`); the worker's tenure projected to the requested `end_date` must stay strictly below the 730-day tenure limit — a projection landing on exactly 730 days is rejected with `ERR_TENURE_LIMIT_EXCEEDED` (422), the boundary is inclusive of rejection; the new assignment's closed interval must not share even a single day with any other non-terminal assignment of the worker — a single touching day is a conflict and yields `ERR_WORKER_DOUBLE_BOOKED` (409); the governing card's half-open window must contain the assignment's `start_date`, else `ERR_CARD_NOT_EFFECTIVE` (422); the referenced `rate_card_id` must be an `ACTIVE` card whose key matches the engagement's `role_code`, `skill_code` and `geo_code`, else `ERR_RATE_CARD_INACTIVE` (422); the engagement must be of type `REQUISITION` — booking against an `SOW` engagement yields `ERR_ENGAGEMENT_TYPE_MISMATCH` (422); the offer must be `ACCEPTED` and must belong to the named engagement, else `ERR_OFFER_NOT_ACCEPTED` (422); and the worker's `supplier_id` must equal the offer's `supplier_id`, else `ERR_WORKER_SUPPLIER_MISMATCH` (422). Only then do the fiscal guards run, in this order: `bill_rate_cents` may not exceed the card's `bill_rate_ceiling_cents` — exactly equal is allowed — else `ERR_RATE_ABOVE_CEILING` (422); the markup transparency check must pass, else `ERR_MARKUP_ABOVE_CAP` (422); and `pay_rate_cents` must be at least the card's `pay_rate_floor_cents`, else `ERR_PAY_BELOW_FLOOR` (422).

The markup transparency check compares the booked rates against the tighter of two caps: the smaller of the card's `max_markup_pct` and the supplier's tier cap — 25% for `PREFERRED`, 20% for `APPROVED`, 15% for `PROBATION`. To keep every implementation honest to the cent, the comparison is performed in integer basis points with no floating-point division anywhere: the booking is allowed only when the bill rate in cents multiplied by ten thousand is less than or equal to the pay rate in cents multiplied by ten thousand plus the applicable cap expressed in basis points — the cap fraction multiplied by ten thousand and rounded to a whole number. The markup percentage displayed to program staff is the bill rate minus the pay rate, divided by the pay rate.

A successfully booked assignment starts `PENDING`; its `supplier_id` is copied from the offer; the referenced offer moves `ACCEPTED` → `CONSUMED`; and the supplier's `offers_filled_count` increases by one. Activation moves the assignment `PENDING` → `ACTIVE` and requires the engagement to be in `FILLING` or `ACTIVE` and the worker to be in `ONBOARDING`, `OFFBOARDING` or `ACTIVE`; as a bubble-up, a worker who was `ONBOARDING` or `OFFBOARDING` becomes `ACTIVE` — which is also how a worker cycles back from `OFFBOARDING` when re-booked. An `ACTIVE` assignment may be extended in place by supplying a `new_end_date` strictly later than the current `end_date`; the extension is rejected with `ERR_TENURE_LIMIT_EXCEEDED` when the tenure projection to `new_end_date` reaches or exceeds 730 days, and on success the assignment's `end_date` simply becomes `new_end_date` — the assignment stays `ACTIVE` throughout. Completion moves `ACTIVE` → `COMPLETED`, stamping `actual_end_date` from the logical clock date, incrementing the supplier's `completed_assignments_count`, and cascading the worker to `OFFBOARDING` when no `PENDING` or `ACTIVE` assignment remains. Manual termination moves `ACTIVE` → `TERMINATED` with `termination_reason` `MANUAL`, the same `actual_end_date` stamping, and the same worker cascade. (`termination_reason` is null unless the assignment is `TERMINATED`, and besides `MANUAL` it can be `ENGAGEMENT_CLOSED` or `CONVERTED` when the termination arrives through those cascades.) Finally, a `ProgramAdmin` may complete offboarding for an `OFFBOARDING` worker — moving the worker to `EXITED` — and may rehire an `EXITED` worker, which returns the worker to `ONBOARDING`; the worker lifecycle is deliberately cyclic.

### 3.6. The Timesheet Billing Cycle

A timesheet is created by a `Worker` against one of that worker's own `ACTIVE` assignments, carrying the `assignment_id`, a `period_start` and `period_end` (the period is inclusive of both ends), and `submitted_hours` — a decimal value with at most two decimal places and at most 60.00, where exactly 60.00 is allowed and anything larger is rejected with `ERR_HOURS_EXCEED_MAX` (422). Only one timesheet may exist per assignment per `period_start`; a second one yields `ERR_DUPLICATE_TIMESHEET_PERIOD` (409). The period must lie entirely inside the assignment's `start_date` to `end_date` span, else `ERR_PERIOD_OUTSIDE_ASSIGNMENT` (422). And both creation and submission require the assignment to be `ACTIVE`; against a non-active assignment the request fails with `ERR_ASSIGNMENT_NOT_ACTIVE` (409). A new timesheet is in `DRAFT`, with `approved_hours`, `provisional_amount_cents`, `final_amount_cents`, `rejection_reason`, `void_reason`, `submitted_by_user_id` and `approved_by_user_id` all null.

Submitting moves a timesheet from `DRAFT` to `SUBMITTED` — and, because rejection is not terminal, also from `REJECTED` back to `SUBMITTED`; the resubmission loop is legal and repeatable. Submission is ownership-checked against the assignment's `worker_id`, stamps `submitted_by_user_id` with the caller's `X-User-ID`, clears any prior `rejection_reason`, and computes the `PROVISIONAL` billing variant: `provisional_amount_cents` is the `submitted_hours` multiplied by the assignment's unclamped `bill_rate_cents`, rounded half up to whole cents. The provisional amount is an estimate only — it is never ledgered.

Approval belongs to the `HiringManager` and computes the `FINAL` variant. The request may supply `approved_hours`; when it does not, `approved_hours` defaults to `submitted_hours`. The effective rate for the final amount is the smaller of the assignment's `bill_rate_cents` and the governing rate card's `bill_rate_ceiling_cents` — the governing card being the `ACTIVE` card for the engagement's key whose half-open window contains the logical clock date at approval time, so the ceiling clamp binds exactly when the governing card changed between submit and approve. `final_amount_cents` is the `approved_hours` multiplied by that effective rate, rounded half up to whole cents. Approval then runs the budget guard: the engagement's `committed_spend_cents` plus this `final_amount_cents` must not exceed `budget_cents` — an exact fit is allowed — otherwise approval is rejected with `ERR_BUDGET_EXCEEDED` (422). On success the approval stamps `approved_by_user_id` and fires a four-link cascade. Link 1: a spend ledger entry of type `TIMESHEET_APPROVED` is appended with a positive `delta_cents` equal to `final_amount_cents`, and the supplier's `spend_ytd_cents` is recomputed. The approval also creates an invoice line for this timesheet on the supplier's single `OPEN` invoice — auto-created when none exists — with the invoice's `line_count` and `subtotal_cents` recomputed per the consolidation rule of §3.8. Link 2: the engagement's `committed_spend_cents` is recomputed. Link 3: when the recomputed committed spend crosses the 95% budget-utilization threshold — from below 95% of `budget_cents` to at or above it — and `budget_audit_raised` is still false, a `BUDGET_UTILIZATION` compliance audit of severity `HIGH` is auto-created against the engagement and the flag is set true, so the audit is raised at most once per engagement. Link 4: creating that audit increments the supplier's `open_violation_count` by one.

Rejection moves `SUBMITTED` → `REJECTED` and records the request's `reason` into `rejection_reason`; the worker may correct and resubmit. Voiding is the finance-side compensation path, available to a `FinanceAnalyst` only while the timesheet is `APPROVED` and the invoice line sourcing it still sits on an `OPEN` invoice — once that invoice has moved on, the void is a wrong-state rejection with `ERR_INVALID_STATE`. A void records the request's `reason` into `void_reason` and compensates every effect of the approval: a ledger entry of type `TIMESHEET_VOIDED` is appended with a negative `delta_cents` equal to the voided `final_amount_cents` and `spend_ytd_cents` is recomputed; the sourcing invoice line is deleted and the invoice's `line_count` and `subtotal_cents` are recomputed; and the engagement's `committed_spend_cents` is recomputed. `VOIDED` is terminal for the timesheet.

Committed spend, referenced by every budget guard above, is defined precisely: the sum of `final_amount_cents` over the engagement's timesheets in `APPROVED` status, plus the sum of `amount_cents` over the engagement's milestones in `ACCEPTED` acceptance status. Timesheets in `DRAFT`, `SUBMITTED`, `REJECTED` or `VOIDED` contribute zero; milestones `DELIVERED` or `REJECTED` contribute zero — the state filter is explicit, not incidental.

### 3.7. SOW Milestones and Deliverable Acceptance

Milestones exist only under `SOW` engagements and are created by a `HiringManager` while the engagement is `OPEN`, `FILLING` or `ACTIVE`; attempting to create one under a `REQUISITION` engagement is rejected with `ERR_ENGAGEMENT_TYPE_MISMATCH`. Creation supplies the milestone `name`, the fixed `amount_cents` paid on acceptance, and the contractual `due_date`. A milestone carries two parallel, independent status dimensions. The acceptance dimension, `acceptance_status`, runs `PENDING` → `DELIVERED` → `ACCEPTED` or `REJECTED`; the payment dimension, `payment_status`, runs `UNINVOICED` → `INVOICED` → `PAID` and is driven purely by invoice events (§3.8) — nothing in the acceptance flow touches it.

Delivery belongs to the awarded supplier: the caller's `X-User-ID` must equal the engagement's `awarded_supplier_id`, the engagement must be `ACTIVE` — delivery against a non-active engagement fails with `ERR_ENGAGEMENT_NOT_ACTIVE` — and the supplier must not be suspended. Delivery works from both `PENDING` and `REJECTED`; the redelivery loop stays open after rejection. Each delivery stamps `delivered_by_supplier_id` with the caller's identity, clears any prior `rejection_reason`, increments the supplier's `milestones_delivered_count` by one (redeliveries count too), and may carry an optional `delivery_note`.

Acceptance belongs to the `HiringManager`, requires `acceptance_status` `DELIVERED`, and runs the same budget guard as timesheet approval: `committed_spend_cents` plus the milestone's `amount_cents` must not exceed `budget_cents`, exact fit allowed, else `ERR_BUDGET_EXCEEDED`. On acceptance the system stamps `accepted_by_user_id`, increments the supplier's `milestones_accepted_count`, and fires the same four-link cascade as timesheet approval: a `MILESTONE_ACCEPTED` ledger entry with a positive `delta_cents` equal to `amount_cents` and a `spend_ytd_cents` recompute; an invoice line attached to the supplier's `OPEN` invoice (auto-created when none) with `line_count` and `subtotal_cents` recomputed; the engagement's `committed_spend_cents` recomputed; and the 95%-crossing `BUDGET_UTILIZATION` audit with its `open_violation_count` increment when the flag allows. The milestone's `payment_status` stays `UNINVOICED` through all of this — acceptance is not invoicing. Rejection of a `DELIVERED` milestone records the request's `reason` into `rejection_reason` and likewise leaves the payment dimension untouched.

### 3.8. Invoice Consolidation and Payment

Invoicing is organized around one invariant: a supplier has at most one `OPEN` invoice at any time. That invoice is usually created lazily — the first billable event (a timesheet approval or milestone acceptance) auto-creates it, with its `period_start` set to the first day of the month containing that first line's event date and its `period_end` set to the last day of that month. A `FinanceAnalyst` may also create an empty invoice manually with an explicit `supplier_id`, `period_start` and `period_end`; when the supplier already has an `OPEN` invoice the manual creation is rejected with `ERR_INVOICE_ALREADY_OPEN` (409).

Each `InvoiceLine` attaches to one invoice via `invoice_id` and sources exactly one event: `timesheet_id` when the line comes from an approved timesheet, `milestone_id` when it comes from an accepted milestone — never both, never neither. The line's `amount_cents` is already a whole-cent integer at attach time, because timesheet finals are rounded per timesheet at approval and milestone amounts are integers by definition. The consolidation rule pins that rounding order: an invoice's `subtotal_cents` is the plain integer sum of its attached lines' `amount_cents`, and `line_count` is their count — rounding happens exclusively per line upstream and never again at invoice level. The counterfactual of summing raw fractional amounts and rounding once at the end is forbidden because it diverges: fractional lines of 22502.5 and 40504.5 would sum-and-round to 63007, while the pinned per-line amounts 22503 and 40505 sum to 63008. Lines whose timesheet is later voided are detached, so they simply drop out of the sum.

Finalization is the `FinanceAnalyst` action that moves an invoice `OPEN` → `FINALIZED`. An invoice with zero lines cannot be finalized — `line_count` must be at least 1, else `ERR_INVOICE_EMPTY` (422). Finalization recomputes `subtotal_cents` per the consolidation rule, then computes the processing fee, the invoice total, and the consolidation savings, in that order. The processing fee is tiered on the pre-fee subtotal — never on the post-fee total: when `subtotal_cents` is below 10,000,000 cents the fee rate is 1.5%; when the subtotal is at or above 10,000,000 cents the rate is 1.0%. The `processing_fee_cents` is the subtotal multiplied by that rate, rounded half up to whole cents, and `total_cents` is the subtotal plus the fee. Keying the tier on the post-fee total would diverge — a subtotal of 9,999,999 cents yields a fee of 150,000 cents and a total of 10,149,999 cents that crosses the threshold, yet the 1.5% rate still applies because the tier was fixed on the pre-fee subtotal. The `consolidation_savings_cents` quantifies the batching benefit against a per-invoice fee baseline of 5,000 cents: it is one less than `line_count`, multiplied by 5,000, whenever `line_count` is at least 1, and zero otherwise — consolidating many lines into one invoice incurs exactly one fee instead of one per line. Finalization stamps `finalized_by_user_id` with the caller's `X-User-ID` and moves every milestone whose line is attached from `UNINVOICED` to `INVOICED` on the payment dimension.

Payment is segregation-of-duties controlled: marking a `FINALIZED` invoice paid requires the caller's `X-User-ID` to differ from the invoice's `finalized_by_user_id`; the same person attempting both steps is rejected with `ERR_SOD_VIOLATION` (403). A successful payment stamps `paid_by_user_id` and moves every attached milestone `INVOICED` → `PAID`. Voiding unwinds a `FINALIZED` invoice: the request's `reason` is recorded into `void_reason`, every attached line is detached and re-attached to a fresh `OPEN` invoice for the supplier (auto-created when none exists), and every milestone whose line was attached reverts from `INVOICED` back to `UNINVOICED`. Both `PAID` and `VOIDED` are terminal. Invoices are listed with filters on `supplier_id` and `status`; invoice lines are reverse-reachable through filters on `invoice_id`, `timesheet_id` and `milestone_id`.

### 3.9. Conversion, Compliance Audits, and Spend Visibility

Converting a contingent worker to an employee begins when a `HiringManager` files a conversion request naming the `worker_id` and the `assignment_id` of the worker's `ACTIVE` assignment; the request is filed in `REQUESTED` status. A worker may have at most one conversion request in `REQUESTED` or `APPROVED` at a time; a second filing is rejected with `ERR_CONVERSION_ALREADY_REQUESTED` (409). At filing, the system snapshots `tenure_days_at_request` (the tenure accumulation of §3.5 evaluated at the logical clock date) and computes the fee — both are immutable thereafter. The fee variant is pinned: `PRORATA` applies only when the engagement's `prorata_conversion` flag is true and the supplier's tier is `PREFERRED`; every other case uses `SCHEDULE`. The base fee is 2,500,000 cents. Under `SCHEDULE`, the fee is a step function of tenure: below 180 days the full base applies; from 180 through 364 days, 75% of the base; from 365 through 544 days, 50%; and at 545 days or more the fee is zero. Under `PRORATA`, the fee decays linearly across a 730-day horizon: the base multiplied by one minus the tenure divided by 730, floored at zero, rounded half up to whole cents. The two variants genuinely differ for identical tenure — at 62 days, for instance, `SCHEDULE` charges the full 2,500,000 cents while `PRORATA` charges 2,287,671 cents. The selected variant and computed amount are stored as `fee_variant` and `fee_cents`, and the worker's `conversion_status` moves to `REQUESTED`.

Disposition belongs to the `ProgramAdmin`. Approval moves the request `REQUESTED` → `APPROVED` and the worker's `conversion_status` to `APPROVED`. Decline records the request's `reason` into `decline_reason` and moves both to `DECLINED`. Completing an `APPROVED` request executes the conversion: the referenced assignment becomes `TERMINATED` with `termination_reason` `CONVERTED` and `actual_end_date` set from the logical clock date, and the worker moves straight to `EXITED` with `conversion_status` `CONVERTED` — offboarding is bypassed entirely on this path.

The compliance audit engine lets a `ProgramAdmin` re-check a booked subject against the card that governs today. A run names exactly one subject — a `timesheet_id` or an `assignment_id`; supplying both or neither is a malformed request under `ERR_VALIDATION`. The run resolves the governing rate card — the `ACTIVE` card matching the engagement's `role_code`, `skill_code` and `geo_code` whose half-open window contains the logical clock date (for a timesheet subject, the card key comes from its assignment's engagement) — and produces at most one finding of each kind per run, each as its own `ComplianceAudit` row. `OVER_RATE` (severity `HIGH`) is raised when the assignment's `bill_rate_cents` exceeds the governing card's `bill_rate_ceiling_cents`. `MARKUP_EXCEEDED` (severity `HIGH`) is raised when the markup transparency check of §3.5 fails against the governing card — again comparing against the tighter of the card cap and the supplier's tier cap. `TENURE_RISK` (severity `LOW`) is raised when the assignment is `ACTIVE` and its worker's `cumulative_tenure_days` has reached 700 days — within 30 days of the 730-day hard limit. Each finding derives its `supplier_id` from the subject (the assignment's supplier, or the timesheet's assignment's supplier), carries a machine-generated `details` explanation, starts in `OPEN` status, and increments the supplier's `open_violation_count` by one. Engagement-level `BUDGET_UTILIZATION` findings raised by the approval cascades instead set the audit's `engagement_id`. The `finding` value is one of `OVER_RATE`, `MARKUP_EXCEEDED`, `TENURE_RISK` or `BUDGET_UTILIZATION`; `severity` is `LOW` or `HIGH` (defaulting to `HIGH`).

Audit disposition walks a strict chain: acknowledging moves `OPEN` → `ACKNOWLEDGED`; from `ACKNOWLEDGED` the audit may be resolved or dismissed — both record the request's `resolution_note`, both are terminal, and both decrement the supplier's `open_violation_count` by one as compensation. Audits are listed with filters on `supplier_id`, `engagement_id`, `timesheet_id`, `assignment_id`, `finding` and `status`.

Spend visibility closes the loop. The ledger is queryable with filters on `supplier_id`, `engagement_id`, `timesheet_id`, `milestone_id`, `invoice_id` and `entry_type`, exposing each entry's signed `delta_cents` and chronological `running_balance_cents`. A consolidated spend summary — available to `ProgramAdmin` and `FinanceAnalyst`, optionally narrowed to one supplier via `supplier_id` — reports five aggregates across the program: `total_committed_cents` (approved spend), `total_invoiced_cents`, `total_paid_cents`, `consolidation_savings_cents` realized through batching, and `open_violations_count`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Creating a new resource returns HTTP 201 with the created resource; actions, state transitions and reads return HTTP 200 (distribution and audit runs, which create new resources, return 201). Every request and response conforms to the envelope of §2.2, and every error carries the `error_id` catalogued in §5. Request and response field-level detail is specified in the §3 narratives for each workflow; this table is the routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/v1/_clock/set_current_utc` | Set the logical clock to `to_iso8601`; returns `current_utc` | ProgramAdmin |
| POST | `/v1/rate-cards` | Create a rate card in `DRAFT` | ProgramAdmin |
| GET | `/v1/rate-cards` | List rate cards; filters `role_code`, `skill_code`, `geo_code`, `status`, `supersedes_id` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| GET | `/v1/rate-cards/{id}` | Get one rate card | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| POST | `/v1/rate-cards/{id}/activate` | `DRAFT` → `ACTIVE`; enforces half-open window non-overlap per key | ProgramAdmin |
| POST | `/v1/rate-cards/{id}/retire` | `ACTIVE` → `RETIRED` | ProgramAdmin |
| POST | `/v1/rate-cards/{id}/revisions` | OCC supersede: create a new `DRAFT` card copying this one with overrides | ProgramAdmin |
| POST | `/v1/suppliers` | Onboard a supplier with an initial tier | ProgramAdmin |
| GET | `/v1/suppliers` | List suppliers; filters `tier`, `status` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| GET | `/v1/suppliers/{id}` | Get one supplier (includes `tier_score`, counters, `spend_ytd_cents`) | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| POST | `/v1/suppliers/{id}/suspend` | `ACTIVE` → `SUSPENDED`; withdraws its `OFFERED` offers | ProgramAdmin |
| POST | `/v1/suppliers/{id}/reinstate` | `SUSPENDED` → `ACTIVE` | ProgramAdmin |
| POST | `/v1/suppliers/{id}/tier-evaluation` | Ops-run checkpoint: recompute tier score and band from counters | ProgramAdmin |
| POST | `/v1/engagements` | Create an engagement in `DRAFT` | HiringManager |
| GET | `/v1/engagements` | List engagements; filters `status`, `engagement_type`, `awarded_supplier_id` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| GET | `/v1/engagements/{id}` | Get one engagement (includes `committed_spend_cents`, `misclassification_risk`) | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| POST | `/v1/engagements/{id}/submit-review` | `DRAFT` → `IN_REVIEW`; computes misclassification risk | HiringManager |
| POST | `/v1/engagements/{id}/classification-decision` | `IN_REVIEW` → `OPEN` (APPROVE) or `IN_REVIEW` → `DRAFT` (REWORK) | ProgramAdmin |
| POST | `/v1/engagements/{id}/distribute` | `OPEN` → `FILLING`; creates offers for the top 3 suppliers, ordered by selection rank | ProgramAdmin |
| POST | `/v1/engagements/{id}/amendments` | OCC amendment of `budget_cents`, `duration_months`, `title` on non-terminal engagements | HiringManager |
| POST | `/v1/engagements/{id}/close` | `OPEN`/`FILLING`/`ACTIVE` → `CLOSED`; cascades assignment termination and worker offboarding | HiringManager |
| GET | `/v1/distribution-offers` | List offers; filters `engagement_id`, `supplier_id`, `status` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst |
| GET | `/v1/distribution-offers/{id}` | Get one offer | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst |
| POST | `/v1/distribution-offers/{id}/respond` | Supplier responds ACCEPT or DECLINE; first ACCEPT bubbles the engagement to `ACTIVE` | SupplierCoordinator |
| POST | `/v1/distribution-offers/{id}/withdraw` | Withdraw an `OFFERED` offer | ProgramAdmin |
| POST | `/v1/distribution-offers/expire-sweep` | Ops-run checkpoint: overdue `OFFERED` offers become `EXPIRED`; returns `expired_count` | ProgramAdmin |
| POST | `/v1/workers` | Register a worker under a supplier | SupplierCoordinator, ProgramAdmin |
| GET | `/v1/workers` | List workers; filters `supplier_id`, `status` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| GET | `/v1/workers/{id}` | Get one worker (includes `cumulative_tenure_days`) | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| POST | `/v1/workers/{id}/offboard-complete` | `OFFBOARDING` → `EXITED` | ProgramAdmin |
| POST | `/v1/workers/{id}/rehire` | `EXITED` → `ONBOARDING` (cyclic rehire) | ProgramAdmin |
| POST | `/v1/assignments` | Book a worker onto a `REQUISITION` engagement via an `ACCEPTED` offer; the offer becomes `CONSUMED` | ProgramAdmin |
| GET | `/v1/assignments` | List assignments; filters `worker_id`, `engagement_id`, `supplier_id`, `rate_card_id`, `offer_id`, `status` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| GET | `/v1/assignments/{id}` | Get one assignment | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| POST | `/v1/assignments/{id}/activate` | `PENDING` → `ACTIVE`; bubbles the worker to `ACTIVE` | ProgramAdmin |
| POST | `/v1/assignments/{id}/extend` | Extend `end_date` via `new_end_date`; tenure projection must stay below 730 days | ProgramAdmin |
| POST | `/v1/assignments/{id}/terminate` | `ACTIVE` → `TERMINATED` (`MANUAL`) | ProgramAdmin |
| POST | `/v1/assignments/{id}/complete` | `ACTIVE` → `COMPLETED`; stamps `actual_end_date` | ProgramAdmin |
| POST | `/v1/timesheets` | Worker creates a `DRAFT` timesheet for an own `ACTIVE` assignment | Worker |
| GET | `/v1/timesheets` | List timesheets; filters `assignment_id`, `status` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| GET | `/v1/timesheets/{id}` | Get one timesheet | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| POST | `/v1/timesheets/{id}/submit` | `DRAFT`/`REJECTED` → `SUBMITTED`; computes `provisional_amount_cents` | Worker |
| POST | `/v1/timesheets/{id}/approve` | `SUBMITTED` → `APPROVED`; final variant with ceiling clamp plus ledger, invoice-line and committed-spend cascades | HiringManager |
| POST | `/v1/timesheets/{id}/reject` | `SUBMITTED` → `REJECTED` | HiringManager |
| POST | `/v1/timesheets/{id}/void` | `APPROVED` → `VOIDED` with full compensation; only while the sourcing invoice is `OPEN` | FinanceAnalyst |
| POST | `/v1/engagements/{id}/milestones` | Create a milestone on an `SOW` engagement | HiringManager |
| GET | `/v1/engagements/{id}/milestones` | List milestones of an engagement | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| GET | `/v1/milestones/{id}` | Get one milestone (both parallel status dimensions) | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst, Worker |
| POST | `/v1/milestones/{id}/deliver` | `PENDING`/`REJECTED` → `DELIVERED`; requires engagement `ACTIVE` and caller is the awarded supplier | SupplierCoordinator |
| POST | `/v1/milestones/{id}/accept` | `DELIVERED` → `ACCEPTED`; ledger, invoice-line and committed-spend cascades | HiringManager |
| POST | `/v1/milestones/{id}/reject` | `DELIVERED` → `REJECTED`; redelivery loop stays open | HiringManager |
| POST | `/v1/invoices` | Manually create an empty `OPEN` invoice for a supplier | FinanceAnalyst |
| GET | `/v1/invoices` | List invoices; filters `supplier_id`, `status` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst |
| GET | `/v1/invoices/{id}` | Get one invoice (`subtotal_cents`, fee, `total_cents`, savings, `line_count`) | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst |
| POST | `/v1/invoices/{id}/finalize` | `OPEN` → `FINALIZED`; computes subtotal, tiered processing fee and consolidation savings; attached milestones become `INVOICED` | FinanceAnalyst |
| POST | `/v1/invoices/{id}/mark-paid` | `FINALIZED` → `PAID`; segregation of duties against the finalizer | FinanceAnalyst |
| POST | `/v1/invoices/{id}/void` | `FINALIZED` → `VOIDED`; lines migrate to a fresh `OPEN` invoice, milestones revert to `UNINVOICED` | FinanceAnalyst |
| GET | `/v1/invoice-lines` | List invoice lines; filters `invoice_id`, `timesheet_id`, `milestone_id` | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst |
| GET | `/v1/invoice-lines/{id}` | Get one invoice line | ProgramAdmin, HiringManager, SupplierCoordinator, FinanceAnalyst |
| POST | `/v1/conversion-requests` | Request conversion-to-employee for a worker on an `ACTIVE` assignment; fee computed at filing | HiringManager |
| GET | `/v1/conversion-requests` | List conversion requests; filters `worker_id`, `assignment_id`, `status` | ProgramAdmin, HiringManager, FinanceAnalyst |
| GET | `/v1/conversion-requests/{id}` | Get one conversion request | ProgramAdmin, HiringManager, FinanceAnalyst |
| POST | `/v1/conversion-requests/{id}/approve` | `REQUESTED` → `APPROVED` | ProgramAdmin |
| POST | `/v1/conversion-requests/{id}/decline` | `REQUESTED` → `DECLINED` | ProgramAdmin |
| POST | `/v1/conversion-requests/{id}/complete` | `APPROVED` → `COMPLETED`; assignment terminated (`CONVERTED`), worker `EXITED` | ProgramAdmin |
| POST | `/v1/compliance-audits/run` | Run a rate-compliance audit on one subject (`timesheet_id` or `assignment_id`); creates and returns findings | ProgramAdmin |
| GET | `/v1/compliance-audits` | List audits; filters `supplier_id`, `engagement_id`, `timesheet_id`, `assignment_id`, `finding`, `status` | ProgramAdmin, HiringManager, FinanceAnalyst |
| GET | `/v1/compliance-audits/{id}` | Get one audit | ProgramAdmin, HiringManager, FinanceAnalyst |
| POST | `/v1/compliance-audits/{id}/acknowledge` | `OPEN` → `ACKNOWLEDGED` | ProgramAdmin |
| POST | `/v1/compliance-audits/{id}/resolve` | `ACKNOWLEDGED` → `RESOLVED`; decrements the supplier's open violation count | ProgramAdmin |
| POST | `/v1/compliance-audits/{id}/dismiss` | `ACKNOWLEDGED` → `DISMISSED`; decrements the supplier's open violation count | ProgramAdmin |
| GET | `/v1/spend-ledger-entries` | List ledger entries; filters `supplier_id`, `engagement_id`, `timesheet_id`, `milestone_id`, `invoice_id`, `entry_type` | ProgramAdmin, FinanceAnalyst |
| GET | `/v1/spend-ledger-entries/{id}` | Get one ledger entry | ProgramAdmin, FinanceAnalyst |
| GET | `/v1/spend/summary` | Consolidated spend visibility across all suppliers (or one when filtered by `supplier_id`) | ProgramAdmin, FinanceAnalyst |

## 5. Error Code Catalogue

The catalogue below is the complete set of machine-readable error identifiers. The conditions that trigger each error are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 |
| `ERR_SUPPLIER_SUSPENDED` | 422 |
| `ERR_TENURE_LIMIT_EXCEEDED` | 422 |
| `ERR_MISCLASSIFICATION_RISK` | 422 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_RATE_CARD_WINDOW_OVERLAP` | 409 |
| `ERR_WORKER_DOUBLE_BOOKED` | 409 |
| `ERR_DUPLICATE_TIMESHEET_PERIOD` | 409 |
| `ERR_CONVERSION_ALREADY_REQUESTED` | 409 |
| `ERR_INVOICE_ALREADY_OPEN` | 409 |
| `ERR_HOURS_EXCEED_MAX` | 422 |
| `ERR_NO_ELIGIBLE_SUPPLIER` | 422 |
| `ERR_PERIOD_OUTSIDE_ASSIGNMENT` | 422 |
| `ERR_CARD_NOT_EFFECTIVE` | 422 |
| `ERR_RATE_CARD_INACTIVE` | 422 |
| `ERR_ENGAGEMENT_TYPE_MISMATCH` | 422 |
| `ERR_OFFER_NOT_ACCEPTED` | 422 |
| `ERR_WORKER_SUPPLIER_MISMATCH` | 422 |
| `ERR_RATE_ABOVE_CEILING` | 422 |
| `ERR_MARKUP_ABOVE_CAP` | 422 |
| `ERR_PAY_BELOW_FLOOR` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_INVOICE_EMPTY` | 422 |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 |
| `ERR_STALE_RATE_CARD_VERSION` | 412 |
