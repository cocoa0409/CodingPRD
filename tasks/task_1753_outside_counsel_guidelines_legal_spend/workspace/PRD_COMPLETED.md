# Outside Counsel Spend API — Product Requirements Document

## 1. Introduction

Corporate legal departments live and die by two instruments: the outside counsel guidelines they publish to their panel firms, and the e-billing pipeline through which those firms submit invoices for review. In practice the two drift apart — guidelines say one thing about staffing, rates, and block billing, while invoices assert another — and legal operations teams spend their cycles reconciling the difference by hand. This document specifies an API that closes that gap. It governs the full outside counsel spend lifecycle: publication of guideline versions and the acknowledgment duty each panel firm owes, registration and qualification of timekeepers, the annual rate card negotiation under capped increases, submission of UTBMS-coded invoices against engaged matters, automated and manual line-item enforcement, the appeals process for rejected charges, monthly accrual collection, matter-level spend forecasting, and a periodic performance scorecard for each panel firm.

The API is mounted under `/legal-departments` and is built around two actors: the in-house legal operations reviewer, who administers the program, and the panel firm user, who bills against it. Every rule described here — rate caps, staffing ratios, acknowledgment windows, budget gates — is enforced deterministically by the server so that both sides see the same numbers, the same states, and the same reasons when a charge is refused.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across the entire API, independent of any single workflow.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, carrying an empty value for either header, or carrying a role value outside the declared set is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly two roles:

- `LegalOpsReviewer` — in-house legal operations staff. This role administers departments, onboards and manages panel firms, publishes guideline versions, creates matters, approves and rejects rate cards, qualifies and disqualifies timekeepers, reviews invoice line items, decides appeals, pays invoices, maintains matter forecasts, recomputes scorecards, and drives the logical clock.
- `PanelFirmUser` — staff at an outside panel firm. This role acknowledges guidelines, accepts matter engagements, drafts and submits rate cards and rate rows, registers timekeepers, submits invoices, voids rejected invoices, files appeals, and submits monthly accruals.

Read access is shared: both roles may call any retrieval or listing operation. Write operations are restricted per endpoint, and a caller whose role is not permitted on an endpoint is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `LegalOpsReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id`. When `X-User-Role` is `PanelFirmUser`, `X-User-ID` is the `id` of the acting `PanelFirm`; ownership checks on any resource that references a `PanelFirm` compare the resource's `panel_firm_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FIRM_MISMATCH`.

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

A request body missing a required field is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422) — the catalogue's catch-all for malformed input. The same error surfaces the explicit value-domain checks noted in §3: an unrecognized `tk_class`, an unrecognized manual `rejection_reason_code`, or a `line_items` payload that is not an array of objects. Beyond these, field values are not otherwise validated.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — an out-of-range `limit` is clamped to the nearest bound rather than rejected, and a non-numeric value falls back to the default. The `offset` parameter skips a number of items from the front of the result set and defaults to 0; a negative `offset` is clamped to 0 and a non-numeric one falls back to the default. All list endpoints sort by creation timestamp in ascending order unless otherwise specified, with ties broken by insertion order (earliest inserted first). The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

Several listings accept optional filter parameters in addition to `limit` and `offset`: panel firms and guideline versions filter by `status`; matters filter by `engagement_status` and `panel_firm_id`; acknowledgments filter by `status` and `guideline_version_id`; rate cards filter by `status` and `effective_year`; timekeepers filter by `qualification_status` and `tk_class`; invoices filter by `status`; line items filter by `review_status`; appeals filter by `status`; and accruals and scorecard snapshots filter by `period_year` and `period_month`. The advisory staffing-ratio read on a matter accepts an optional `basis` parameter.

### 2.4. Common Resource Properties

Every resource in the system — `LegalDepartment`, `PanelFirm`, `GuidelineVersion`, `GuidelineAcknowledgment`, `Matter`, `RateCard`, `Timekeeper`, `TimekeeperRate`, `Invoice`, `InvoiceLineItem`, `Appeal`, `Accrual`, `MatterForecast`, and `ScorecardSnapshot` — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation, including mutations caused by cascades and derived-field recomputation.

Newly created resources return `201 Created`; operations that modify an existing resource return `200 OK`.

### 2.5. The Logical Clock

All time-dependent behavior in the system — acknowledgment due dates, timestamp stamping, scorecard windows, temporal validations — reads from a single logical clock, never from wall-clock time. At server startup, before any clock operation has been invoked, the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only test-driving capability, available exclusively to `LegalOpsReviewer`, advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. The clock is set to exactly the supplied instant — the server does not require it to lie after the current reading — and an unparseable `to_iso8601` is refused with `ERR_INVALID_TEMPORAL`. Advancing the clock triggers a system sweep: every guideline acknowledgment whose due date has passed transitions from `PENDING` to `OVERDUE`, as detailed in §3.2. Server-stamped timestamps such as `acknowledged_at` and `submitted_at` always record the logical clock at the moment of the transition.

### 2.6. Nested Resource Retrieval

Resource paths are deeply hierarchical — a line item, for instance, is addressed through its department, matter, and invoice, as in the pattern formed by `{deptId}`, `{matterId}`, `{invoiceId}`, and `{lineId}`. The server validates path identifiers strictly left to right: it confirms the legal department exists before it looks for the panel firm or matter within it, confirms that scope before descending further, and rejects the request immediately with `ERR_NOT_FOUND` at the first identifier that does not resolve within its expected parent scope. Existence validation in this order precedes any state or business-rule evaluation.

### 2.7. Monetary Values, Hours, and Rounding

All money in the system is represented as integer cents — budgets, rates, line amounts, invoice totals, accruals, and forecast figures alike. Hours are carried at two-decimal precision. The monetary rounding rules are deliberately uneven across the domain, and each is stated where its calculation lives:

- A line item's `amount_cents` is pinned at the moment of computation as the line's `hours` multiplied by its `rate_cents`, rounded half-up to a whole cent. This per-line rounding happens before any aggregation; invoice-level totals are plain integer sums over already-rounded line amounts and undergo no further rounding.
- Rate-card ceilings during the annual increase cap computation truncate down to a whole cent (floor) at the ceiling step, as detailed in §3.4.
- Staffing-ratio percentages are computed at four-decimal precision before any comparison against the configured band, and the boundary comparison uses that rounded value.
- Scorecard metrics and the weighted overall score are each rounded half-up to two decimal places, with the per-metric rounding applied before the weighting, as detailed in §3.7.

### 2.8. Optimistic Concurrency Control

Two creation endpoints are guarded by optimistic concurrency control, because creating the child legitimately mutates the parent and a client working from a stale read would silently build on a version it never observed:

- Submitting an invoice against a matter may carry `expected_matter_version`, set to the matter's `version` as last observed by the client; the field is optional on this endpoint, and when it is omitted no staleness check is applied. Invoice creation itself advances the matter's `version` (its spend caches are maintained as a side effect), so a second submission carrying the previously observed version is deterministically stale. If the supplied value does not match the matter's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a rate card under a panel firm requires `expected_panel_firm_version`, matched against the firm's current `version` in the same way. Rate-card creation advances the firm's `version`, so a replayed creation intent is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; concurrency rejection applies only to these two guarded writes, with the stale-version check evaluated late in the validation pipeline described in §2.9.

### 2.9. Validation Pipeline and Priority Order

When several checks could reject the same request, the server applies them in a fixed priority order so that the surfaced error is deterministic; where a §3 narrative pins an endpoint-specific order among these checks, that order governs over this generic ladder (guideline publication in §3.2, for instance, evaluates its temporal guard before its overlap and notice-gap guards):

1. Authentication: both headers present and the role value recognized — otherwise `ERR_UNAUTHENTICATED`.
2. Authorization: the acting role is permitted on the endpoint — otherwise `ERR_FORBIDDEN`.
3. Existence: path resources resolve, left to right per §2.6 — otherwise `ERR_NOT_FOUND`.
4. State legality: the target resource is in a state from which the requested transition is permitted — otherwise `ERR_INVALID_STATE`.
5. Regulatory controls during invoice auto-review: block-billing detection, rate-exceeds enforcement, and unapproved-timekeeper enforcement run at the line level. These never fail the request itself; they set a `rejection_reason_code` on the offending lines, and they run before any fiscal check.
6. Referential integrity: foreign references resolve within scope — the billed timekeeper belongs to the engaged firm, the engaged firm is `ACTIVE`, an accrual's period is not already matched — otherwise `ERR_REFERENTIAL_INTEGRITY`.
7. Uniqueness and window constraints: a firm's `invoice_number` must not repeat (`ERR_DUPLICATE_INVOICE_NUMBER`), a rate card's `effective_year` must not collide with another in-flight or approved card (`ERR_RATE_CARD_YEAR_CONFLICT`), and a guideline publication must honor the notice gap (`ERR_NOTICE_GAP_VIOLATION`).
8. Temporal rules: a billing period must end after it starts, a guideline's `effective_date` must not lie in the past, and an accrual period must not lie in the future — otherwise `ERR_INVALID_TEMPORAL`.
9. Fiscal gates, evaluated last: the matter budget gate marks over-budget lines with the `OVER_BUDGET` reason at line level, and the stale-version checks of §2.8 reject with `ERR_STALE_VERSION`.

### 2.10. Hierarchical Consistency and Cascading Effects

State changes on a parent propagate to keep the hierarchy coherent, and the server performs these reconciliations automatically without requiring the client to touch each affected resource. Publishing a guideline supersedes its predecessor and spawns an acknowledgment duty on every active firm. Suspending a firm auto-denies its open appeals, which in turn flips the underlying line items and recomputes their invoices. Offboarding a firm closes its engaged matters, disqualifies its pending timekeepers, and rejects its in-flight rate cards. Granting an appeal reinstates the line, recomputes the invoice, and credits the matter. Every resource mutated along a cascade — whether it is the primary target or a downstream casualty — has its `updated_at` refreshed and its `version` incremented by one.

## 3. Business Logic & Workflows

### 3.1. Department Configuration and the Panel Firm Lifecycle

A `LegalOpsReviewer` establishes the root tenant by creating a legal department with a display `name` and five policy knobs that drive enforcement elsewhere in the system: `annual_rate_increase_cap_pct`, the hard cap in percent applied to per-timekeeper rate increases between consecutive effective years; `partner_ratio_min_pct` and `partner_ratio_max_pct`, the inclusive band within which the partner-hour share on each open matter must sit; `guideline_notice_days`, the mandatory gap between the effective dates of consecutive published guideline versions; and `acknowledgment_window_days`, the number of days a panel firm has to acknowledge a published guideline before its duty sours. The department's `id`, `version`, and timestamps follow §2.4, and every resource subsequently created under it records the owning department in its `legal_department_id`.

Panel firms join a department through onboarding by a `LegalOpsReviewer`, who supplies the `firm_name`. A new firm starts in `ACTIVE` status with `version` 1. Its `status` walks a small lifecycle: `ACTIVE` firms may bill and submit rate cards; a `LegalOpsReviewer` may move a firm `ACTIVE → SUSPENDED`, which blocks new invoices and the submission of rate cards (draft cards may still be created while suspended); a suspended firm may be reinstated `SUSPENDED → ACTIVE`; and a suspended firm may be offboarded `SUSPENDED → OFFBOARDED`, which is terminal. Each transition bumps the firm's `version`.

Suspension carries a two-hop cascade. Every appeal in `SUBMITTED` or `UNDER_REVIEW` status that was filed on any line item of any invoice belonging to the firm auto-transitions to `DENIED`, with its `resolution_note` set to `AUTO_DENIED_FIRM_SUSPENDED`. Each such auto-denied appeal then triggers the standard denial cascade described in §3.6: the underlying line item flips from `REJECTED` to `UPHELD`, and the parent invoice's `approved_total_cents` is recomputed. Offboarding is guarded: it is refused with `ERR_FIRM_HAS_OPEN_INVOICES` while any invoice under any matter engaged to the firm remains in `SUBMITTED` or `UNDER_REVIEW`. When it proceeds, every matter engaged to the firm in `ENGAGED` status transitions to `CLOSED`, every timekeeper of the firm still `PENDING` transitions to `DISQUALIFIED`, every rate card of the firm in `DRAFT` or `SUBMITTED` transitions to `REJECTED`, and the firm's `version` increments.

### 3.2. Guideline Publication and the Acknowledgment Duty

Guidelines are versioned documents. A `LegalOpsReviewer` creates a guideline version with a human `version_label` such as "OCG-2026-A" and an `effective_date`; the version begins in `DRAFT`. Publication is the pivotal act, and three guards apply, evaluated in the order stated here: the `effective_date` must not lie in the past (else `ERR_INVALID_TEMPORAL`); no other published version of the same department may carry an `effective_date` on or after the one being published (else `ERR_GUIDELINE_OVERLAP`); and, when another version is currently published, the gap between the new `effective_date` and the prior version's `effective_date` must be at least `guideline_notice_days` days (else `ERR_NOTICE_GAP_VIOLATION`).

A successful publication transitions the version `DRAFT → PUBLISHED`, stamps its `published_at` with the logical clock, increments its `version`, and cascades in two directions. The previously `PUBLISHED` version of the department, if any, transitions to `SUPERSEDED`. Simultaneously, for every panel firm of the department whose `status` is `ACTIVE`, the server cascade-creates one acknowledgment record in `PENDING` status; each record binds the firm through its `panel_firm_id` and the version through its `guideline_version_id`, and its `acknowledged_at` remains null until the firm acts.

Acknowledgment is the firm's duty, performed by a `PanelFirmUser`. The acting user's firm must equal the acknowledgment's `panel_firm_id`, or the attempt fails with `ERR_FIRM_MISMATCH`. A successful acknowledgment — from either `PENDING` or `OVERDUE` — transitions the record to `ACKNOWLEDGED`, stamps `acknowledged_at` with the logical clock, and increments its `version`; `ACKNOWLEDGED` is terminal. The overdue transition is system-driven: when the logical clock (§2.5) advances past the parent guideline version's publication timestamp plus the department's `acknowledgment_window_days`, the sweep flips the still-`PENDING` record to `OVERDUE` and increments its `version`. A firm that missed the window can still acknowledge late; the record then shows the `OVERDUE → ACKNOWLEDGED` path it took. Acknowledgment listings can be narrowed by `status` or by `guideline_version_id`.

### 3.3. Matter Engagement

Legal work is billed against matters. A `LegalOpsReviewer` creates a matter under a department by naming the engaged `panel_firm_id`, a `title`, and a `budget_cents` cap in cents; the named `panel_firm_id` must resolve to a firm of the same department (`ERR_REFERENTIAL_INTEGRITY`), and no firm-status precondition applies at creation. The matter begins with `engagement_status` `PENDING`, and its two spend counters start at zero: `billed_to_date_cents`, the running sum of approved line amounts across all non-voided invoices, and `accrual_outstanding_cents`, the sum of accrual amounts not yet matched by a submitted invoice.

The engagement is accepted by the firm: a `PanelFirmUser` moves the matter `PENDING → ENGAGED`, which increments the matter's `version`. Three preconditions guard acceptance — the acting user's firm must equal the matter's `panel_firm_id` (`ERR_FIRM_MISMATCH`), the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`), and, if the department has any currently `PUBLISHED` guideline version, the firm must hold an `ACKNOWLEDGED` acknowledgment for it (`ERR_ACK_OUTSTANDING`). A firm with a stale or missing acknowledgment must cure that first, per §3.2.

Closure and reopening belong to the `LegalOpsReviewer`. Closing a matter (`ENGAGED → CLOSED`) is refused with `ERR_MATTER_HAS_OPEN_INVOICES` while any of its invoices sits in `SUBMITTED` or `UNDER_REVIEW`, and refused with `ERR_MATTER_HAS_OPEN_APPEALS` while any appeal on any of its line items sits in `SUBMITTED` or `UNDER_REVIEW`. A closed matter is not strictly terminal: reopening returns it `CLOSED → ENGAGED`, provided the engaged firm is `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`). Matter listings filter by `engagement_status` or `panel_firm_id`.

An advisory staffing-ratio read is available on any matter. By default — `basis` equal to `BILLED_HOURS` — it answers on the billed-hours basis described in §3.5; passing `basis` as `HEADCOUNT` switches to the headcount-weighted basis — the share of `PARTNER` timekeepers among the firm's `QUALIFIED` timekeepers, ignoring actual billing entirely. The two bases deliberately produce different percentages for identical underlying data. The `basis` value is matched case-insensitively, and any value other than `HEADCOUNT` falls back to the billed-hours basis. When the share cannot be computed — no qualifying billed hours on the billed-hours basis, or no `QUALIFIED` timekeepers on the headcount basis — the read answers `partner_share_pct` null and `compliant` true. The response carries the computed `partner_share_pct`, the `basis` used, and a `compliant` flag reflecting the department's band.

### 3.4. Timekeepers and the Annual Rate Card Cycle

Before a firm can bill, its people must be known and its rates approved. A `PanelFirmUser` registers a timekeeper under its own firm — the acting user's firm must equal the path firm (`ERR_FIRM_MISMATCH`) — with a `full_name` and a `tk_class` of `PARTNER`, `ASSOCIATE`, or `PARALEGAL`, a value outside the three being refused with `ERR_REFERENTIAL_INTEGRITY`; the classification matters because it drives the rate-increase sub-cap below. A new timekeeper's `qualification_status` is `PENDING` until a `LegalOpsReviewer` qualifies them (`PENDING → QUALIFIED`), which requires the employing firm to be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`). A qualified timekeeper may later be disqualified (`QUALIFIED → DISQUALIFIED`, terminal), but only while no line item in `PENDING` review status still references them — otherwise the transition is refused with `ERR_TIMEKEEPER_HAS_PENDING_LINES`. Timekeeper listings filter by `qualification_status` or `tk_class`.

Rates are negotiated annually through rate cards. A `PanelFirmUser` creates a card under its own firm — the acting user's firm must equal the path firm (`ERR_FIRM_MISMATCH`) — by declaring its `effective_year` and — because this write is OCC-guarded per §2.8 — the firm's expected version in `expected_panel_firm_version`; a value that does not match the firm's current `version` (or is not an integer) is rejected with `ERR_STALE_VERSION`. The card starts in `DRAFT`, its creation increments the firm's `version`, and the firm then adds one rate row per timekeeper, each row carrying the `timekeeper_id` and the proposed `hourly_rate_cents` for that year; every row records its parent `rate_card_id`, and its `approved_rate_cents` stays null until approval. Rows may only be added while the card is in `DRAFT`; adding a row requires the acting user's firm to own the card (`ERR_FIRM_MISMATCH`) and the referenced `timekeeper_id` to belong to that firm (`ERR_REFERENTIAL_INTEGRITY`), and the server does not enforce one-row-per-timekeeper, so duplicate rows for the same timekeeper may coexist.

Submission (`DRAFT → SUBMITTED`) stamps `submitted_at` with the logical clock, increments the card's `version`, and is guarded by four checks: the acting user's firm must own the card (`ERR_FIRM_MISMATCH`); the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`); every timekeeper referenced by a rate row on the card must be `QUALIFIED` (`ERR_TIMEKEEPER_NOT_QUALIFIED`); and no other card of the same firm may already cover the same `effective_year` in `SUBMITTED` or `APPROVED` status (`ERR_RATE_CARD_YEAR_CONFLICT`).

Approval is where the annual increase cap bites. When a `LegalOpsReviewer` approves a submitted card (`SUBMITTED → APPROVED`), each rate row's `approved_rate_cents` is set as follows. The cap applicable to a row depends on the timekeeper's class: the full `annual_rate_increase_cap_pct` for a `PARTNER`, eighty percent of that cap for an `ASSOCIATE`, and sixty percent of it for a `PARALEGAL`. The prior baseline is the same firm's most recent `APPROVED` card with a strictly earlier `effective_year`, selected by descending effective year with ties broken by ascending creation time — never by identifier. If no such prior card exists, the proposed rates stand as the baseline and no clamping occurs. Otherwise, for each row, the ceiling is the prior card's approved rate for the same timekeeper multiplied by one plus the applicable sub-cap percentage divided by one hundred, truncated down to a whole cent; the row's `approved_rate_cents` is then the smaller of its proposed `hourly_rate_cents` and that ceiling. A timekeeper absent from the prior card is clamped by nothing. Violators are clamped rather than blocked — approval itself is never refused over the cap. Approval also supersedes: any other card of the firm in `APPROVED` status transitions to `SUPERSEDED`, and the approved card's `version` increments.

Rejection sends a card `SUBMITTED → REJECTED`, and the firm may loop a rejected card back `REJECTED → DRAFT` through revision — the acting user's firm must own the card (`ERR_FIRM_MISMATCH`) — edit its rows, and submit again. Card listings filter by `status` or `effective_year`.

### 3.5. Invoice Submission and Automated Rule Enforcement

Billing enters the system when a `PanelFirmUser` submits an invoice against an `ENGAGED` matter. The payload carries the firm-supplied `invoice_number`, the `billing_period_start`, and the exclusive `billing_period_end`, the optional OCC field `expected_matter_version` (§2.8), and a `line_items` collection — which may be empty or omitted altogether — whose entries each name the billing `timekeeper_id`, exactly one `utbms_task_code` such as "L120", a free-text `narrative`, the `hours` billed at two-decimal precision, and the `rate_cents` asserted in cents per hour. Submission guards stack up in pipeline order: the matter must be `ENGAGED` (`ERR_INVALID_STATE`); the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`); the acting user's firm must equal the matter's engaged firm (`ERR_FIRM_MISMATCH`); every line's timekeeper must belong to the engaged firm (`ERR_REFERENTIAL_INTEGRITY`); the `invoice_number` must be unique across that firm's invoices (`ERR_DUPLICATE_INVOICE_NUMBER`); the period end must be later than the period start (`ERR_INVALID_TEMPORAL`); and a stale expected version, when one is supplied, is rejected with `ERR_STALE_VERSION`. The new invoice resolves its `panel_firm_id` from the matter at creation, records its `matter_id`, starts in `SUBMITTED`, and immediately auto-transitions to `UNDER_REVIEW`; creation also increments the matter's `version`. Each persisted line item records its parent `invoice_id` alongside the submitted fields.

Auto-review runs the rule engine over each line item in a fixed evaluation order. First, the block-billing detector: if a line's `narrative` contains two or more distinct task-code markers — an uppercase letter "L" immediately followed by three digits, matched case-sensitively — over and above the single structured `utbms_task_code` on the line, the line is rejected with reason `BLOCK_BILLING`. Otherwise, if the asserted `rate_cents` exceeds the timekeeper's `approved_rate_cents` for the billing period's year — the year taken from `billing_period_start` — the line is rejected with `RATE_EXCEEDS_APPROVED`. Otherwise, if the timekeeper is not `QUALIFIED`, the line is rejected with `UNAPPROVED_TIMEKEEPER`. Otherwise, if the asserted rate matches no approved rate on the firm's card for that year yet sits below the approved rate, the line is left `PENDING` for manual review — the rate-not-on-card case. Otherwise the line is approved. The card supplying the approved rate for a year is the firm's `APPROVED` card with that exact `effective_year`, or — absent an exact match — the most recent `APPROVED` card with a strictly earlier `effective_year` (ties broken by ascending creation time); when no such card exists, or the timekeeper has no row on it, no approved rate applies, both rate comparisons are skipped, and a `QUALIFIED` timekeeper's line is approved. Each line's `amount_cents` is pinned per §2.7 as `hours` times `rate_cents` rounded half-up, and the invoice's `submitted_total_cents` is the sum of all line amounts as submitted.

One fiscal overlay runs at line level during auto-review, per the priority ladder in §2.9, without ever failing the request: the budget gate walks the lines the rule engine approved, in submission order, accumulating a running total on top of the matter's current `billed_to_date_cents`, and any line whose `amount_cents` would push that running total strictly over the matter's `budget_cents` is rejected with reason `OVER_BUDGET` — catalogued as `ERR_OVER_BUDGET` — its amount left out of the accumulation, so a later, smaller line may still pass. The staffing-ratio rule, by contrast, is never enforced by auto-review: it backs only the advisory read of §3.3 and the manual `STAFFING_RATIO` rejection reason of §3.6. On the billed-hours basis, partner hours are the summed `hours` of lines billed by `PARTNER` timekeepers in the approved-equivalent statuses `APPROVED`, `ADJUSTED_APPROVED`, or `REINSTATED` across all non-`VOID` invoices of the matter; total hours are the same sum over all classes in those statuses; the ratio is null when total hours are zero, and otherwise the partner share times one hundred, computed at four-decimal precision. A ratio strictly below `partner_ratio_min_pct` or strictly above `partner_ratio_max_pct` is a violation — exactly at either boundary is compliant.

The invoice's aggregate status derives from its lines and is re-evaluated after every line-item review action and every appeal resolution: while any line remains `PENDING` the invoice stays `UNDER_REVIEW`; when every line sits in `APPROVED`, `ADJUSTED_APPROVED`, or `REINSTATED`, the invoice becomes `APPROVED`; when every line sits in `REJECTED` or `UPHELD`, it becomes `REJECTED`; anything in between — including an invoice with no line items at all — yields `PARTIALLY_APPROVED`. The invoice's `approved_total_cents` is recomputed on the same triggers: a line contributes its `adjusted_amount_cents` when `ADJUSTED_APPROVED`, its `amount_cents` when `APPROVED` or `REINSTATED`, and zero in any other status. Landing on `APPROVED` or `PARTIALLY_APPROVED` from a state that had not booked spend books spend — the matter's `billed_to_date_cents` increases by the invoice's `approved_total_cents` — and consumes accruals: every unmatched accrual whose period, compared as the first instant of its (`period_year`, `period_month`) month, falls on or after `billing_period_start` and before `billing_period_end` has its `matched_invoice_id` set to this invoice, and the matter's `accrual_outstanding_cents` decreases by each matched accrual's `amount_cents`. A derivation that moves between the two booked states, or re-derives the state the invoice already held, books nothing again. A fully `REJECTED` invoice books nothing.

### 3.6. Manual Review, Corrections, and the Appeals Process

Lines left `PENDING` by the rule engine — and any line a reviewer disagrees with — are worked by a `LegalOpsReviewer`. A pending line may be approved outright (`PENDING → APPROVED`). It may be adjust-approved (`PENDING → ADJUSTED_APPROVED`) with a reviewer-supplied `adjusted_amount_cents`, which must be at least zero and strictly less than the line's `amount_cents` (`ERR_INVALID_ADJUSTMENT`). Or it may be rejected (`PENDING → REJECTED`) with a `rejection_reason_code` drawn from `BLOCK_BILLING`, `RATE_EXCEEDS_APPROVED`, `UNAPPROVED_TIMEKEEPER`, `STAFFING_RATIO`, or `OVER_BUDGET`; the reason may be omitted, leaving the line's `rejection_reason_code` null, and an unrecognized value is refused with `ERR_REFERENTIAL_INTEGRITY`. Every one of these actions recomputes the invoice's `approved_total_cents` and re-derives the aggregate status per §3.5.

Corrections after an invoice has booked spend follow a compensating-debit discipline. While the parent invoice is `APPROVED` or `PARTIALLY_APPROVED`, a reviewer may still reject a line that is `APPROVED` or `ADJUSTED_APPROVED`; the rejection sets its `rejection_reason_code`, recomputes the invoice totals with the line excluded, and the matter's `billed_to_date_cents` decreases by the line's prior contribution — its `amount_cents` for a formerly approved line, or its `adjusted_amount_cents` for a formerly adjust-approved line.

The firm's remedy against a rejection is the appeal. A `PanelFirmUser` may file an appeal, with a free-text `rationale`, against any line whose `review_status` is `REJECTED`; the acting user's firm must match the invoice's `panel_firm_id` (`ERR_FIRM_MISMATCH`), and nothing prevents filing while an earlier appeal on the same line is still open. The appeal record binds the line through `invoice_line_item_id` and starts in `SUBMITTED`. A `LegalOpsReviewer` claims it (`SUBMITTED → UNDER_REVIEW`), then resolves it in one of two terminal directions, recording a `resolution_note` when one is supplied. Granting (`UNDER_REVIEW → GRANTED`) fires a three-hop cascade: the line transitions `REJECTED → REINSTATED` and its `rejection_reason_code` is cleared; the invoice's `approved_total_cents` is recomputed with the line's amount included again; and the matter's `billed_to_date_cents` increases by the line's `amount_cents` as a compensating credit on top of whatever was already booked — the credit is unconditional, so when the same grant lands a previously unbooked invoice on an approval state, the §3.5 booking of the recomputed `approved_total_cents` happens first and the credit stacks on top. Denying (`UNDER_REVIEW → DENIED`) flips the line `REJECTED → UPHELD` and recomputes the invoice totals with no change in amount. Both resolutions increment the appeal's `version`, and appeal listings filter by `status`.

Payment freezes the money. A `LegalOpsReviewer` may pay an `APPROVED` invoice at any time; a `PARTIALLY_APPROVED` invoice may be paid only once no appeal on any of its lines remains in `SUBMITTED` or `UNDER_REVIEW` (`ERR_OPEN_APPEALS`); paying from any other state is refused with `ERR_INVALID_STATE`. Payment transitions the invoice to `PAID`, increments its `version`, and freezes `final_payable_cents` to the then-current `approved_total_cents`. Until payment, `final_payable_cents` simply tracks `approved_total_cents`; afterwards it is never recomputed, so two reads of the same invoice — one taken while an appeal was pending, one after payment — can legitimately show different payable figures for identical line data. A fully `REJECTED` invoice may instead be voided by the firm (`REJECTED → VOID`) — the acting user's firm must match the invoice's `panel_firm_id` (`ERR_FIRM_MISMATCH`) — which increments the invoice's `version` and touches nothing else, the parent matter's state and counters left exactly as they stand. `PAID` and `VOID` are terminal. Invoice listings filter by `status`, and line listings by `review_status`.

### 3.7. Accruals, Matter Forecasts, and Firm Performance Scorecards

Between invoices, firms report unbilled estimates. A `PanelFirmUser` submits a monthly accrual on a matter with a `period_year`, a `period_month` from 1 to 12, and an `amount_cents` estimate; the acting user's firm must equal the matter's engaged firm (`ERR_FIRM_MISMATCH`), and a `period_month` outside 1–12 — or a period value that is not an integer — is refused with `ERR_INVALID_TEMPORAL`. The period must not lie in the future (`ERR_INVALID_TEMPORAL`), and a period already matched to an invoice cannot be filed again (`ERR_REFERENTIAL_INTEGRITY`); an unmatched accrual, by contrast, blocks nothing, so several unmatched accruals may coexist for the same period. Creation adds the accrual's `amount_cents` to the matter's `accrual_outstanding_cents` and triggers recomputation of the forecast's work-in-progress figure. Timeliness matters for the scorecard below: an accrual counts as on time when submitted on or before the fifth day of the month following its period. Accrual listings filter by `period_year` and `period_month`.

Each matter carries a one-to-one forecast. A `LegalOpsReviewer` creates-or-replaces it by setting `lifecycle_estimate_cents`, the department's estimate of total matter spend; reading a forecast that has never been written answers `ERR_NOT_FOUND`, and reading one back returns three figures governed by a pinned evaluation order that removes any circularity. First, `billed_to_date_cents` is read from the matter as already maintained by the invoice side effects of §3.5. Second, `wip_estimate_cents` is computed as the sum of `amount_cents` over the matter's accruals whose `matched_invoice_id` is still null. Third, `variance_cents` is the lifecycle estimate minus the sum of billed-to-date and work-in-progress; a negative variance signals a projected overrun. Under no circumstances does the work-in-progress figure depend on the variance or vice versa. The forecast recomputes whenever the estimate is set, whenever an accrual is created, whenever an invoice is created or lands on an approval state, after every line-item review action and every appeal grant, and on every read of the forecast; each recomputation refreshes the forecast's `updated_at` and bumps its `version` per §2.4.

Firm performance is measured by scorecard snapshots. A `LegalOpsReviewer` triggers a recomputation for a given `period_year` and `period_month`; the server computes four metrics over the trailing twelve-month window ending at the logical clock — the window opens one year before the clock reading, same month-day and time of day with the day clamped to that month's length, and is inclusive at both ends; records counted are those whose `created_at` falls within it, and a metric whose denominator is empty computes as zero — rounds each metric half-up to two decimal places, then weights them into an `overall_pct` also rounded half-up to two decimal places. The metrics: `on_time_ack_pct`, the percent of the firm's guideline acknowledgments acknowledged on or before their due date; `rejection_rate_pct`, the percent of the firm's reviewed line items whose final `review_status` is `REJECTED` or `UPHELD`; `appeal_uphold_rate_pct`, the percent of the firm's resolved appeals that were `DENIED`; and `accrual_timeliness_pct`, the percent of the firm's accruals submitted on or before the fifth of the following month. Higher is better for acknowledgment timeliness and accrual timeliness, and worse for rejection and appeal-uphold rates, so the weighting inverts the latter two: the overall score is thirty percent of `on_time_ack_pct`, plus thirty percent of one hundred minus `rejection_rate_pct`, plus twenty percent of one hundred minus `appeal_uphold_rate_pct`, plus twenty percent of `accrual_timeliness_pct`. Persisting the snapshot also refreshes the firm's `scorecard_overall_pct` — null on a firm until its first snapshot persists — to the new snapshot's `overall_pct`, and snapshot listings filter by `period_year` and `period_month`.

## 4. Endpoint Definitions

Operations that create a new resource — a department, firm, guideline version, matter, rate card, timekeeper, rate row, invoice, appeal, accrual, or scorecard snapshot — return `201 Created`. Operations that modify an existing resource, including all state transitions and the create-or-update forecast write, return `200 OK`. Request payloads, preconditions, and side effects are specified in §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/legal-departments` | Create a legal department (root tenant) | LegalOpsReviewer |
| GET | `/legal-departments` | List legal departments (paginated) | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}` | Get a legal department | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms` | Onboard a panel firm | LegalOpsReviewer |
| GET | `/legal-departments/{deptId}/panel-firms` | List panel firms of a department | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}` | Get a panel firm | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/suspend` | Suspend a panel firm | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/reinstate` | Reinstate a suspended panel firm | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/offboard` | Offboard a suspended panel firm (terminal) | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/guideline-versions` | Create a draft guideline version | LegalOpsReviewer |
| GET | `/legal-departments/{deptId}/guideline-versions` | List guideline versions of a department | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/guideline-versions/{gvId}` | Get a guideline version | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/guideline-versions/{gvId}/publish` | Publish a guideline version (supersedes prior; spawns acknowledgments) | LegalOpsReviewer |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/acknowledgments` | List acknowledgments for a firm | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/acknowledgments/{ackId}` | Get a single acknowledgment | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/acknowledgments/{ackId}/acknowledge` | Firm acknowledges a guideline version | PanelFirmUser |
| POST | `/legal-departments/{deptId}/matters` | Create a matter engaged to a panel firm | LegalOpsReviewer |
| GET | `/legal-departments/{deptId}/matters` | List matters of a department | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}` | Get a matter | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/matters/{matterId}/engage` | Firm accepts engagement | PanelFirmUser |
| POST | `/legal-departments/{deptId}/matters/{matterId}/close` | Close a matter | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/reopen` | Reopen a closed matter | LegalOpsReviewer |
| GET | `/legal-departments/{deptId}/matters/{matterId}/staffing-ratio` | Advisory staffing-ratio computation (`basis` defaults to billed hours) | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards` | Create a DRAFT rate card (OCC-guarded on firm version) | PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards` | List rate cards of a firm | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}` | Get a rate card | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}/submit` | Submit rate card for approval | PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}/approve` | Approve rate card (cap clamping; supersedes prior approved card) | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}/reject` | Reject a submitted rate card | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}/revise` | Return a REJECTED rate card to DRAFT | PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/timekeepers` | Register a timekeeper under a firm | PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/timekeepers` | List timekeepers of a firm | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/timekeepers/{tkId}` | Get a timekeeper | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/timekeepers/{tkId}/qualify` | Mark timekeeper QUALIFIED | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/timekeepers/{tkId}/disqualify` | Mark timekeeper DISQUALIFIED | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}/rates` | Add a per-timekeeper rate to a DRAFT rate card | PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}/rates` | List rates on a card | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/rate-cards/{cardId}/rates/{rateId}` | Get a specific rate row | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices` | Submit an e-billing invoice (OCC-guarded on matter version; auto-review runs) | PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/invoices` | List invoices of a matter | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}` | Get an invoice | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/pay` | Mark invoice PAID (freezes final payable) | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/void` | Void a REJECTED invoice | PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items` | List line items of an invoice | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}` | Get a line item | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/approve` | Manually approve a PENDING line item | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/adjust` | Adjust-approve a PENDING line item | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/reject` | Manually reject a line item with reason | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/appeals` | Firm appeals a REJECTED line item | PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/appeals` | List appeals on a line item | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/appeals/{appealId}` | Get an appeal | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/appeals/{appealId}/claim` | Reviewer claims an appeal | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/appeals/{appealId}/grant` | Grant an appeal (line reinstated; totals and matter credited) | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/invoices/{invoiceId}/line-items/{lineId}/appeals/{appealId}/deny` | Deny an appeal (line upheld) | LegalOpsReviewer |
| POST | `/legal-departments/{deptId}/matters/{matterId}/accruals` | Submit a monthly accrual | PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/accruals` | List accruals of a matter | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/matters/{matterId}/accruals/{accrualId}` | Get an accrual | LegalOpsReviewer, PanelFirmUser |
| PUT | `/legal-departments/{deptId}/matters/{matterId}/forecast` | Create-or-update the matter's lifecycle forecast (1:1) | LegalOpsReviewer |
| GET | `/legal-departments/{deptId}/matters/{matterId}/forecast` | Read the matter's forecast (1:1) | LegalOpsReviewer, PanelFirmUser |
| POST | `/legal-departments/{deptId}/panel-firms/{firmId}/scorecards/recompute` | Compute and persist a scorecard snapshot for a period | LegalOpsReviewer |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/scorecards` | List scorecard snapshots of a firm | LegalOpsReviewer, PanelFirmUser |
| GET | `/legal-departments/{deptId}/panel-firms/{firmId}/scorecards/{snapshotId}` | Get a scorecard snapshot | LegalOpsReviewer, PanelFirmUser |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps overdue acknowledgments | LegalOpsReviewer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_FIRM_MISMATCH` | 403 Forbidden |
| `ERR_FIRM_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACK_OUTSTANDING` | 409 Conflict |
| `ERR_GUIDELINE_OVERLAP` | 409 Conflict |
| `ERR_NOTICE_GAP_VIOLATION` | 409 Conflict |
| `ERR_TIMEKEEPER_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_RATE_CARD_YEAR_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_INVOICE_NUMBER` | 409 Conflict |
| `ERR_INVALID_TEMPORAL` | 422 Unprocessable Entity |
| `ERR_MATTER_HAS_OPEN_INVOICES` | 409 Conflict |
| `ERR_MATTER_HAS_OPEN_APPEALS` | 409 Conflict |
| `ERR_FIRM_HAS_OPEN_INVOICES` | 409 Conflict |
| `ERR_OPEN_APPEALS` | 409 Conflict |
| `ERR_INVALID_ADJUSTMENT` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_TIMEKEEPER_HAS_PENDING_LINES` | 409 Conflict |
| `ERR_OVER_BUDGET` | 422 Unprocessable Entity |
